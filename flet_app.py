import flet as ft
import re
import os
import sqlite3
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from io import BytesIO
from datetime import datetime
import time

# -------------------- إعدادات عامة --------------------

SUBJECT_KEYS = ["Programming", "Mathematics", "Network", "Security"]

DEFAULT_YEAR_MAX = 30.0
DEFAULT_MID_MAX = 30.0
DEFAULT_FINAL_MAX = 40.0
W_YEAR, W_MID, W_FINAL = 0.30, 0.30, 0.40


# -------------------- دوال مساعدة --------------------

def normalize_email(email: str) -> str:
    email = email.lower().strip()
    email = re.sub(r'[^a-zA-Z0-9]', '_', email)
    return f"db_{email}.db"


def get_conn(db_path):
    return sqlite3.connect(db_path, check_same_thread=False)


def ensure_db_and_migrate(db_path):
    if not os.path.exists(db_path):
        open(db_path, "a").close()
    with get_conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS students (name TEXT, uni TEXT PRIMARY KEY, active INTEGER DEFAULT 1)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY AUTOINCREMENT, uni TEXT, subject TEXT, year REAL, mid REAL, final REAL, percent REAL, letter TEXT)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS subject_names (subject_key TEXT PRIMARY KEY, display_name TEXT)"
        )
        for key in SUBJECT_KEYS:
            cur.execute(
                "INSERT OR IGNORE INTO subject_names (subject_key, display_name) VALUES (?, ?)",
                (key, key),
            )
        conn.commit()


def get_subject_names(db_path):
    with get_conn(db_path) as conn:
        df = pd.read_sql_query("SELECT subject_key, display_name FROM subject_names", conn)
    names = {row["subject_key"]: row["display_name"] for _, row in df.iterrows()}
    for k in SUBJECT_KEYS:
        if k not in names:
            names[k] = k
    return names


def update_subject_names(db_path, new_names: dict):
    with get_conn(db_path) as conn:
        cur = conn.cursor()
        for key, disp in new_names.items():
            cur.execute(
                "UPDATE subject_names SET display_name=? WHERE subject_key=?",
                (disp, key),
            )
        conn.commit()


def compute_percent_from_defaults(y, m, f):
    try:
        y_pct = (float(y) / DEFAULT_YEAR_MAX) * 100
    except:
        y_pct = 0
    try:
        m_pct = (float(m) / DEFAULT_MID_MAX) * 100
    except:
        m_pct = 0
    try:
        f_pct = (float(f) / DEFAULT_FINAL_MAX) * 100
    except:
        f_pct = 0
    pct = round(y_pct * W_YEAR + m_pct * W_MID + f_pct * W_FINAL, 2)
    return pct


def percent_to_letter(p):
    try:
        p = float(p)
    except:
        return ""
    if p >= 95:
        return "A+"
    if p >= 90:
        return "A"
    if p >= 85:
        return "B+"
    if p >= 80:
        return "B"
    if p >= 75:
        return "C+"
    if p >= 70:
        return "C"
    if p >= 60:
        return "D"
    return "F"


def add_student(db_path, name, uni):
    try:
        with get_conn(db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO students (name, uni, active) VALUES (?, ?, 1)",
                (name, uni),
            )
            conn.commit()
        return True, None
    except sqlite3.IntegrityError:
        return False, "University number already exists"
    except Exception as e:
        return False, str(e)


def list_students_raw(db_path):
    with get_conn(db_path) as conn:
        df = pd.read_sql_query(
            "SELECT name, uni, active FROM students WHERE active=1 ORDER BY uni",
            conn,
        )
    return df


def update_student_info(db_path, old_uni, new_name, new_uni):
    try:
        with get_conn(db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE students SET name=?, uni=? WHERE uni=?",
                (new_name, new_uni, old_uni),
            )
            cur.execute(
                "UPDATE subjects SET uni=? WHERE uni=?",
                (new_uni, old_uni),
            )
            conn.commit()
        return True, None
    except sqlite3.IntegrityError:
        return False, "University number already exists"
    except Exception as e:
        return False, str(e)


def hard_delete_student(db_path, uni):
    with get_conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM subjects WHERE uni=?", (uni,))
        cur.execute("DELETE FROM students WHERE uni=?", (uni,))
        conn.commit()


def get_subjects_for_student(db_path, uni):
    with get_conn(db_path) as conn:
        df = pd.read_sql_query(
            "SELECT subject, year, mid, final, percent, letter FROM subjects WHERE uni=?",
            conn,
            params=(uni,),
        )
    return df


def upsert_subject_grade(db_path, uni, subject_key, year, mid, final):
    pct = compute_percent_from_defaults(year, mid, final)
    letter = percent_to_letter(pct)
    with get_conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM subjects WHERE uni=? AND subject=?",
            (uni, subject_key),
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE subjects SET year=?, mid=?, final=?, percent=?, letter=? WHERE id=?",
                (year, mid, final, pct, letter, row[0]),
            )
        else:
            cur.execute(
                "INSERT INTO subjects (uni, subject, year, mid, final, percent, letter) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (uni, subject_key, year, mid, final, pct, letter),
            )
        conn.commit()
    return pct, letter


def clear_subject_grade(db_path, uni, subject_key):
    with get_conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM subjects WHERE uni=? AND subject=?",
            (uni, subject_key),
        )
        conn.commit()


def build_main_table(db_path):
    students = list_students_raw(db_path)
    subject_names = get_subject_names(db_path)
    if students.empty:
        for key in SUBJECT_KEYS:
            students[subject_names[key]] = ""
        students["Average"] = ""
        return students[
            ["name", "uni"] + [subject_names[k] for k in SUBJECT_KEYS] + ["Average"]
        ]
    with get_conn(db_path) as conn:
        subj_df = pd.read_sql_query(
            "SELECT uni, subject, percent, letter FROM subjects",
            conn,
        )
    if subj_df.empty:
        for key in SUBJECT_KEYS:
            students[subject_names[key]] = ""
        students["Average"] = ""
        return students[
            ["name", "uni"] + [subject_names[k] for k in SUBJECT_KEYS] + ["Average"]
        ]
    subj_df["display"] = subj_df.apply(
        lambda r: f"{r['percent']:.1f} ({r['letter']})"
        if r["percent"] is not None
        else "",
        axis=1,
    )
    pivot = subj_df.pivot(index="uni", columns="subject", values="display")
    avg_df = subj_df.pivot(index="uni", columns="subject", values="percent")
    for key in SUBJECT_KEYS:
        if key not in avg_df.columns:
            avg_df[key] = None
    avg_series = avg_df[SUBJECT_KEYS].mean(axis=1, skipna=True)
    avg_letter = avg_series.apply(
        lambda p: percent_to_letter(p) if pd.notna(p) else ""
    )
    avg_display = avg_series.combine(
        avg_letter, lambda p, l: f"{p:.1f} ({l})" if p == p else ""
    )
    result = students.set_index("uni")
    for key in SUBJECT_KEYS:
        col_name = subject_names[key]
        if key in pivot.columns:
            result[col_name] = pivot[key]
        else:
            result[col_name] = ""
    result["Average"] = avg_display
    result.reset_index(inplace=True)
    cols = ["name", "uni"] + [subject_names[k] for k in SUBJECT_KEYS] + ["Average"]
    return result[cols]


def generate_pdf(db_path, students_df):
    subject_names = get_subject_names(db_path)
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 40
    y = height - margin
    c.setFont("Helvetica-Bold", 14)
    c.drawString(margin, y, "Student Term Report")
    c.setFont("Helvetica", 10)
    y -= 20
    c.drawString(
        margin,
        y,
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    )
    y -= 30
    cols = (
        ["Name", "University number"]
        + [subject_names[k] for k in SUBJECT_KEYS]
        + ["Average"]
    )
    col_x = [margin + i * 90 for i in range(len(cols))]
    c.setFont("Helvetica-Bold", 9)
    for i, h in enumerate(cols):
        c.drawString(col_x[i], y, h)
    y -= 14
    c.setFont("Helvetica", 8)
    for _, row in students_df.iterrows():
        if y < 60:
            c.showPage()
            y = height - margin
            c.setFont("Helvetica-Bold", 9)
            for i, h in enumerate(cols):
                c.drawString(col_x[i], y, h)
            y -= 14
            c.setFont("Helvetica", 8)
        vals = [str(row["name"]), str(row["uni"])]
        for key in SUBJECT_KEYS:
            col_name = subject_names[key]
            vals.append(str(row.get(col_name, "")))
        vals.append(str(row.get("Average", "")))
        for i, v in enumerate(vals):
            c.drawString(col_x[i], y, v)
        y -= 14
    c.save()
    buffer.seek(0)
    return buffer.getvalue()


# -------------------- تطبيق Flet الرئيسي --------------------

def main(page: ft.Page):
    page.title = "Student Term System"
    page.window_width = 1100
    page.window_height = 700
    page.theme_mode = "light"

    state = {
        "db_path": None,
        "subject_names": {},
        "selected_uni": None,
    }

    # -------------------- شاشة تسجيل الدخول --------------------

    email_field = ft.TextField(label="Enter your email", width=400)
    login_error = ft.Text("", color="red")

    def do_login(e):
        email = email_field.value.strip()
        if "@" not in email or "." not in email:
            login_error.value = "Please enter a valid email"
            page.update()
            return
        db_path = normalize_email(email)
        state["db_path"] = db_path
        ensure_db_and_migrate(db_path)
        state["subject_names"] = get_subject_names(db_path)
        build_main_ui(email)

    login_view = ft.Column(
        [
            ft.Text("Student Term System", size=32, weight="bold", color="#1f4e79"),
            ft.Text("Login", size=20, weight="bold"),
            email_field,
            ft.Button("Login", on_click=do_login),
            login_error,
        ],
        alignment="center",
        horizontal_alignment="center",
    )

    # -------------------- واجهة التطبيق بعد تسجيل الدخول --------------------

    def build_main_ui(email):
        page.controls.clear()

        db_path = normalize_email(email)
        state["db_path"] = db_path
        ensure_db_and_migrate(db_path)
        state["subject_names"] = get_subject_names(db_path)

        header = ft.Column(
            [
                ft.Text("Student Term System", size=28, weight="bold", color="#1f4e79"),
                ft.Text(f"Logged in as: {email}", size=12, color="#666666"),
                ft.Divider(),
            ]
        )

        # -------------------- تبويب Home --------------------

        home_table = ft.DataTable(columns=[], rows=[], expand=True)
        home_info = ft.Text("")

        def refresh_home():
            main_df = build_main_table(state["db_path"])
            state["subject_names"] = get_subject_names(state["db_path"])
            if main_df.empty:
                home_info.value = "No students yet."
                home_table.columns = []
                home_table.rows = []
            else:
                home_info.value = ""
                cols = [ft.DataColumn(ft.Text(c)) for c in main_df.columns]
                rows = []
                for _, row in main_df.iterrows():
                    cells = [ft.DataCell(ft.Text(str(row[c]))) for c in main_df.columns]
                    rows.append(ft.DataRow(cells=cells))
                home_table.columns = cols
                home_table.rows = rows
            page.update()

        def download_csv(e):
            main_df = build_main_table(state["db_path"])
            if main_df.empty:
                return
            csv_data = main_df.to_csv(index=False).encode("utf-8")
            file_name = f"students_term_{int(time.time())}.csv"
            with open(file_name, "wb") as f:
                f.write(csv_data)

        def download_pdf_action(e):
            main_df = build_main_table(state["db_path"])
            if main_df.empty:
                return
            pdf_bytes = generate_pdf(state["db_path"], main_df)
            file_name = f"students_term_{int(time.time())}.pdf"
            with open(file_name, "wb") as f:
                f.write(pdf_bytes)

        home_tab_content = ft.Column(
            [
                ft.Text("All Students Summary", size=20, weight="bold", color="#1f4e79"),
                home_info,
                home_table,
                ft.Row(
                    [
                        ft.Button("Refresh", on_click=lambda e: refresh_home()),
                        ft.Button("Download CSV", on_click=download_csv),
                        ft.Button("Download PDF", on_click=download_pdf_action),
                    ]
                ),
            ],
            expand=True,
        )

        # -------------------- تبويب Students --------------------

        student_name_field = ft.TextField(label="Student Name", width=300)
        student_uni_field = ft.TextField(label="University Number", width=300)
        student_msg = ft.Text("", color="red")

        subject_name_fields = {
            key: ft.TextField(
                label=f"Subject name for {key}",
                width=300,
                value=state["subject_names"].get(key, key),
            )
            for key in SUBJECT_KEYS
        }
        subject_msg = ft.Text("", color="green")

        def add_student_action(e):
            name = student_name_field.value.strip()
            uni = student_uni_field.value.strip()
            if not name or not uni:
                student_msg.value = "Please enter name and university number"
                student_msg.color = "red"
                page.update()
                return
            ok, err = add_student(state["db_path"], name, uni)
            if ok:
                student_msg.value = "Student added successfully"
                student_msg.color = "green"
                student_name_field.value = ""
                student_uni_field.value = ""
                refresh_home()
            else:
                student_msg.value = err or "Failed to add student"
                student_msg.color = "red"
            page.update()

        def save_subject_names_action(e):
            new_names = {k: subject_name_fields[k].value for k in SUBJECT_KEYS}
            update_subject_names(state["db_path"], new_names)
            state["subject_names"] = get_subject_names(state["db_path"])
            subject_msg.value = "Subject names updated"
            page.update()
            refresh_home()

        students_tab_content = ft.Column(
            [
                ft.Text("Student Management", size=20, weight="bold", color="#1f4e79"),
                ft.Row([student_name_field, student_uni_field]),
                ft.Button("Add Student", on_click=add_student_action),
                student_msg,
                ft.Divider(),
                ft.Text("Subject Settings", size=18, weight="bold", color="#1f4e79"),
                ft.Column(list(subject_name_fields.values())),
                ft.Button("Save Subject Names", on_click=save_subject_names_action),
                subject_msg,
            ],
            expand=True,
        )

        # -------------------- تبويب Grades --------------------

        grades_msg = ft.Text("", color="red")
        students_dropdown = ft.Dropdown(width=400, options=[], label="Select Student")
        selected_student_info = ft.Text("")
        edit_name_field = ft.TextField(label="Edit Name", width=300)
        edit_uni_field = ft.TextField(label="Edit University Number", width=300)
        edit_msg = ft.Text("", color="red")

        delete_msg = ft.Text("", color="red")

        grades_table = ft.DataTable(columns=[], rows=[], expand=True)

        subject_dropdown = ft.Dropdown(width=300, label="Select Subject")
        year_input = ft.TextField(label="Year Work (out of 30)", width=150, value="0")
        mid_input = ft.TextField(label="Midterm (out of 30)", width=150, value="0")
        final_input = ft.TextField(label="Final (out of 40)", width=150, value="0")
        grade_msg = ft.Text("", color="green")

        def refresh_students_dropdown():
            df = list_students_raw(state["db_path"])
            if df.empty:
                students_dropdown.options = []
                students_dropdown.value = None
                selected_student_info.value = "No students yet. Add a student in the Students tab."
            else:
                opts = [
                    ft.dropdown.Option(f"{row['uni']} — {row['name']}")
                    for _, row in df.iterrows()
                ]
                students_dropdown.options = opts
            page.update()

        def on_select_student(e):
            val = students_dropdown.value
            if not val:
                return
            uni = val.split(" — ")[0]
            state["selected_uni"] = uni
            df = list_students_raw(state["db_path"])
            row = df[df["uni"] == uni]
            if row.empty:
                selected_student_info.value = "Selected student not found"
                page.update()
                return
            row = row.iloc[0]
            selected_student_info.value = f"Selected Student: {row['name']} ({row['uni']})"
            edit_name_field.value = row["name"]
            edit_uni_field.value = row["uni"]
            refresh_grades_table()
            refresh_subject_dropdown()
            page.update()

        def refresh_grades_table():
            uni = state.get("selected_uni")
            if not uni:
                grades_table.columns = []
                grades_table.rows = []
                page.update()
                return
            subj_df = get_subjects_for_student(state["db_path"], uni)
            subj_df = subj_df.copy()
            subj_df["subject"] = subj_df["subject"].apply(
                lambda k: state["subject_names"].get(k, k)
            )
            if subj_df.empty:
                grades_table.columns = []
                grades_table.rows = []
            else:
                cols = [ft.DataColumn(ft.Text(c)) for c in subj_df.columns]
                rows = []
                for _, row in subj_df.iterrows():
                    cells = [ft.DataCell(ft.Text(str(row[c]))) for c in subj_df.columns]
                    rows.append(ft.DataRow(cells=cells))
                grades_table.columns = cols
                grades_table.rows = rows
            page.update()

        def refresh_subject_dropdown():
            display_subjects = [state["subject_names"][k] for k in SUBJECT_KEYS]
            subject_dropdown.options = [ft.dropdown.Option(d) for d in display_subjects]
            if display_subjects:
                subject_dropdown.value = display_subjects[0]
            page.update()

        def save_student_info_action(e):
            uni = state.get("selected_uni")
            if not uni:
                edit_msg.value = "No student selected"
                edit_msg.color = "red"
                page.update()
                return
            new_name = edit_name_field.value.strip()
            new_uni = edit_uni_field.value.strip()
            if not new_name or not new_uni:
                edit_msg.value = "Fields cannot be empty"
                edit_msg.color = "red"
                page.update()
                return
            ok, err = update_student_info(state["db_path"], uni, new_name, new_uni)
            if ok:
                edit_msg.value = "Student info updated"
                edit_msg.color = "green"
                state["selected_uni"] = new_uni
                refresh_students_dropdown()
                refresh_home()
            else:
                edit_msg.value = err or "Failed to update student info"
                edit_msg.color = "red"
            page.update()

        def delete_student_action(e):
            uni = state.get("selected_uni")
            if not uni:
                delete_msg.value = "No student selected"
                delete_msg.color = "red"
                page.update()
                return
            hard_delete_student(state["db_path"], uni)
            delete_msg.value = "Student deleted"
            delete_msg.color = "green"
            state["selected_uni"] = None
            refresh_students_dropdown()
            refresh_home()
            grades_table.columns = []
            grades_table.rows = []
            selected_student_info.value = ""
            page.update()

        def save_grade_action(e):
            uni = state.get("selected_uni")
            if not uni:
                grade_msg.value = "No student selected"
            else:
                try:
                    y_val = float(year_input.value or 0)
                    m_val = float(mid_input.value or 0)
                    f_val = float(final_input.value or 0)
                except:
                    grade_msg.value = "Invalid numbers"
                    grade_msg.color = "red"
                    page.update()
                    return
                if (
                    y_val > DEFAULT_YEAR_MAX
                    or m_val > DEFAULT_MID_MAX
                    or f_val > DEFAULT_FINAL_MAX
                ):
                    grade_msg.value = "One of the grades exceeds the maximum allowed"
                    grade_msg.color = "red"
                    page.update()
                    return
                display = subject_dropdown.value
                inv_map = {v: k for k, v in state["subject_names"].items()}
                subject_key = inv_map[display]
                pct, letter = upsert_subject_grade(
                    state["db_path"], uni, subject_key, y_val, m_val, f_val
                )
                grade_msg.value = f"Saved — {display}: {pct}% — {letter}"
                grade_msg.color = "green"
                refresh_grades_table()
                refresh_home()
            page.update()

        def clear_grade_action(e):
            uni = state.get("selected_uni")
            if not uni:
                grade_msg.value = "No student selected"
            else:
                display = subject_dropdown.value
                inv_map = {v: k for k, v in state["subject_names"].items()}
                subject_key = inv_map[display]
                clear_subject_grade(state["db_path"], uni, subject_key)
                grade_msg.value = "Grade cleared"
                grade_msg.color = "green"
                refresh_grades_table()
                refresh_home()
            page.update()

        grades_tab_content = ft.Column(
            [
                ft.Text("Manage Student Grades", size=20, weight="bold", color="#1f4e79"),
                students_dropdown,
                ft.Button("Load Student", on_click=on_select_student),
                selected_student_info,
                ft.Text("Edit Student Info", size=16, weight="bold"),
                ft.Row([edit_name_field, edit_uni_field]),
                ft.Button("Save Student Info", on_click=save_student_info_action),
                edit_msg,
                ft.Text("Delete Student", size=16, weight="bold"),
                ft.Button("Delete Student", on_click=delete_student_action, bgcolor="red", color="white"),
                delete_msg,
                ft.Divider(),
                ft.Text("Student Grades", size=16, weight="bold"),
                grades_table,
                ft.Text("Add / Edit Grade", size=16, weight="bold"),
                subject_dropdown,
                ft.Row([year_input, mid_input, final_input]),
                ft.Row(
                    [
                        ft.Button("Save Grade", on_click=save_grade_action),
                        ft.Button("Clear Grade", on_click=clear_grade_action),
                    ]
                ),
                grade_msg,
            ],
            expand=True,
        )

        # -------------------- تبويب Account --------------------

        account_msg = ft.Text(f"Logged in as: {email}")

        def logout_action(e):
            page.controls.clear()
            page.add(login_view)
            page.update()

        account_tab_content = ft.Column(
            [
                ft.Text("Account", size=20, weight="bold", color="#1f4e79"),
                account_msg,
                ft.Button("Logout", on_click=logout_action),
            ],
            expand=True,
        )

        # -------------------- إنشاء التبويبات بصيغة Flet الجديدة --------------------

        tabs = ft.Tabs(
            selected_index=0,
            tabs=[
                ft.Tab(label="Home", content=home_tab_content),
                ft.Tab(label="Students", content=students_tab_content),
                ft.Tab(label="Grades", content=grades_tab_content),
                ft.Tab(label="Account", content=account_tab_content),
            ],
            expand=1,
        )

        page.add(header, tabs)
        page.update()

        refresh_home()
        refresh_students_dropdown()
        refresh_subject_dropdown()

    # أول ما يفتح البرنامج → صفحة تسجيل الدخول
    page.add(login_view)
    page.update()


if __name__ == "__main__":
    ft.app(target=main)
