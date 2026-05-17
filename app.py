import streamlit as st
import re
import os
import sqlite3
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from io import BytesIO
from datetime import datetime
import time
from streamlit_cookies_manager import EncryptedCookieManager

st.set_page_config(page_title="Student Term System", layout="wide")

cookies = EncryptedCookieManager(
    prefix="student_app_",
    password="my-secret-password-123"
)

if not cookies.ready():
    st.stop()

def save_login(email):
    cookies["logged_in"] = "yes"
    cookies["email"] = email
    cookies.save()

def load_login():
    if cookies.get("logged_in") == "yes":
        return cookies.get("email")
    return None

def logout():
    cookies["logged_in"] = "no"
    cookies["email"] = ""
    cookies.save()
    st.session_state.clear()
    st.rerun()

def normalize_email(email):
    email = email.lower().strip()
    email = re.sub(r'[^a-zA-Z0-9]', '_', email)
    return f"db_{email}.db"

saved_email = load_login()

if saved_email:
    st.session_state["user_email"] = saved_email
    st.session_state["user_db"] = normalize_email(saved_email)
else:
    st.write("Login")
    email = st.text_input("Enter your email")
    if st.button("Login"):
        if "@" not in email or "." not in email:
            st.error("Please enter a valid email")
        else:
            save_login(email)
            st.session_state["user_email"] = email
            st.session_state["user_db"] = normalize_email(email)
            st.rerun()
    st.stop()

DB = st.session_state["user_db"]

def get_conn():
    return sqlite3.connect(DB, check_same_thread=False)

SUBJECT_KEYS = ["Programming", "Mathematics", "Network", "Security"]

def ensure_db_and_migrate():
    if not os.path.exists(DB):
        open(DB, "a").close()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS students (name TEXT, uni TEXT PRIMARY KEY, active INTEGER DEFAULT 1)")
        cur.execute("CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY AUTOINCREMENT, uni TEXT, subject TEXT, year REAL, mid REAL, final REAL, percent REAL, letter TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS subject_names (subject_key TEXT PRIMARY KEY, display_name TEXT)")
        for key in SUBJECT_KEYS:
            cur.execute("INSERT OR IGNORE INTO subject_names (subject_key, display_name) VALUES (?, ?)", (key, key))
        conn.commit()

def get_subject_names():
    with get_conn() as conn:
        df = pd.read_sql_query("SELECT subject_key, display_name FROM subject_names", conn)
    names = {row["subject_key"]: row["display_name"] for _, row in df.iterrows()}
    for k in SUBJECT_KEYS:
        if k not in names:
            names[k] = k
    return names

def update_subject_names(new_names: dict):
    with get_conn() as conn:
        cur = conn.cursor()
        for key, disp in new_names.items():
            cur.execute("UPDATE subject_names SET display_name=? WHERE subject_key=?", (disp, key))
        conn.commit()

DEFAULT_YEAR_MAX = 30.0
DEFAULT_MID_MAX = 30.0
DEFAULT_FINAL_MAX = 40.0
W_YEAR, W_MID, W_FINAL = 0.30, 0.30, 0.40

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
    if p >= 95: return "A+"
    if p >= 90: return "A"
    if p >= 85: return "B+"
    if p >= 80: return "B"
    if p >= 75: return "C+"
    if p >= 70: return "C"
    if p >= 60: return "D"
    return "F"

def add_student(name, uni):
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO students (name, uni, active) VALUES (?, ?, 1)", (name, uni))
            conn.commit()
        return True, None
    except sqlite3.IntegrityError:
        return False, "University number already exists"
    except Exception as e:
        return False, str(e)

def list_students_raw():
    with get_conn() as conn:
        df = pd.read_sql_query("SELECT name, uni, active FROM students WHERE active=1 ORDER BY uni", conn)
    return df

def update_student_info(old_uni, new_name, new_uni):
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE students SET name=?, uni=? WHERE uni=?", (new_name, new_uni, old_uni))
            cur.execute("UPDATE subjects SET uni=? WHERE uni=?", (new_uni, old_uni))
            conn.commit()
        return True, None
    except sqlite3.IntegrityError:
        return False, "University number already exists"
    except Exception as e:
        return False, str(e)

def hard_delete_student(uni):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM subjects WHERE uni=?", (uni,))
        cur.execute("DELETE FROM students WHERE uni=?", (uni,))
        conn.commit()

def get_subjects_for_student(uni):
    with get_conn() as conn:
        df = pd.read_sql_query("SELECT subject, year, mid, final, percent, letter FROM subjects WHERE uni=?", conn, params=(uni,))
    return df

def upsert_subject_grade(uni, subject_key, year, mid, final):
    pct = compute_percent_from_defaults(year, mid, final)
    letter = percent_to_letter(pct)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM subjects WHERE uni=? AND subject=?", (uni, subject_key))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE subjects SET year=?, mid=?, final=?, percent=?, letter=? WHERE id=?", (year, mid, final, pct, letter, row[0]))
        else:
            cur.execute("INSERT INTO subjects (uni, subject, year, mid, final, percent, letter) VALUES (?, ?, ?, ?, ?, ?, ?)", (uni, subject_key, year, mid, final, pct, letter))
        conn.commit()
    return pct, letter

def clear_subject_grade(uni, subject_key):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM subjects WHERE uni=? AND subject=?", (uni, subject_key))
        conn.commit()

def build_main_table():
    students = list_students_raw()
    subject_names = get_subject_names()
    if students.empty:
        for key in SUBJECT_KEYS:
            students[subject_names[key]] = ""
        students["Average"] = ""
        return students[["name", "uni"] + [subject_names[k] for k in SUBJECT_KEYS] + ["Average"]]
    with get_conn() as conn:
        subj_df = pd.read_sql_query("SELECT uni, subject, percent, letter FROM subjects", conn)
    if subj_df.empty:
        for key in SUBJECT_KEYS:
            students[subject_names[key]] = ""
        students["Average"] = ""
        return students[["name", "uni"] + [subject_names[k] for k in SUBJECT_KEYS] + ["Average"]]
    subj_df["display"] = subj_df.apply(lambda r: f"{r['percent']:.1f} ({r['letter']})" if r["percent"] is not None else "", axis=1)
    pivot = subj_df.pivot(index="uni", columns="subject", values="display")
    avg_df = subj_df.pivot(index="uni", columns="subject", values="percent")
    for key in SUBJECT_KEYS:
        if key not in avg_df.columns:
            avg_df[key] = None
    avg_series = avg_df[SUBJECT_KEYS].mean(axis=1, skipna=True)
    avg_letter = avg_series.apply(lambda p: percent_to_letter(p) if pd.notna(p) else "")
    avg_display = avg_series.combine(avg_letter, lambda p, l: f"{p:.1f} ({l})" if p == p else "")
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

def generate_pdf(students_df):
    subject_names = get_subject_names()
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 40
    y = height - margin
    c.setFont("Helvetica-Bold", 14)
    c.drawString(margin, y, "Student Term Report")
    c.setFont("Helvetica", 10)
    y -= 20
    c.drawString(margin, y, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    y -= 30
    cols = ["Name", "University number"] + [subject_names[k] for k in SUBJECT_KEYS] + ["Average"]
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
    return buffer

def safe_rerun():
    try:
        st.experimental_rerun()
    except:
        try:
            st.experimental_set_query_params(_refresh=int(time.time()))
        except:
            pass

ensure_db_and_migrate()
subject_names = get_subject_names()

tab_home, tab_students, tab_grades, tab_account = st.tabs(["Home", "Students", "Grades", "Account"])

with tab_home:
    main_df = build_main_table()
    st.dataframe(main_df, use_container_width=True)
    if not main_df.empty:
        csv = main_df.to_csv(index=False).encode("utf-8")
        st.download_button("Download CSV", data=csv, file_name="students_term.csv", mime="text/csv")
        pdf_buffer = generate_pdf(main_df)
        st.download_button("Download PDF", data=pdf_buffer, file_name="students_term_report.pdf", mime="application/pdf")

with tab_students:
    name = st.text_input("Student Name")
    uni = st.text_input("University Number")
    if st.button("Add Student"):
        if name.strip() and uni.strip():
            ok, err = add_student(name.strip(), uni.strip())
            if ok:
                st.success("Student added successfully")
                safe_rerun()
            else:
                st.error(err or "Failed to add student")
        else:
            st.error("Please enter name and university number")
    new_names = {}
    for key in SUBJECT_KEYS:
        new_names[key] = st.text_input(f"Subject name for {key}", value=subject_names[key], key=f"subname_{key}")
    if st.button("Save Subject Names"):
        update_subject_names(new_names)
        st.success("Subject names updated")
        safe_rerun()

with tab_grades:
    students_raw = list_students_raw()
    if students_raw.empty:
        st.info("No students yet.")
    else:
        options = students_raw.apply(lambda r: f"{r['uni']} — {r['name']}", axis=1).tolist()
        selected_opt = st.selectbox("Select Student", [""] + options)
        if selected_opt:
            selected_uni = selected_opt.split(" — ")[0]
            st.session_state["selected_uni"] = selected_uni
        if "selected_uni" in st.session_state:
            uni = st.session_state["selected_uni"]
            student_row = students_raw[students_raw["uni"] == uni]
            if not student_row.empty:
                student_row = student_row.iloc[0]
                st.write(f"Selected Student: {student_row['name']} ({student_row['uni']})")
                new_name = st.text_input("Edit Name", value=student_row["name"])
                new_uni = st.text_input("Edit University Number", value=student_row["uni"])
                if st.button("Save Student Info"):
                    if not new_name.strip() or not new_uni.strip():
                        st.error("Fields cannot be empty")
                    else:
                        ok, err = update_student_info(uni, new_name.strip(), new_uni.strip())
                        if ok:
                            st.success("Student info updated")
                            st.session_state["selected_uni"] = new_uni.strip()
                            safe_rerun()
                        else:
                            st.error(err or "Failed to update student info")
                if st.button("Delete Student"):
                    hard_delete_student(uni)
                    st.success("Student deleted")
                    if "selected_uni" in st.session_state:
                        del st.session_state["selected_uni"]
                    safe_rerun()
                subj_df = get_subjects_for_student(uni)
                if not subj_df.empty:
                    subj_df = subj_df.copy()
                    subj_df["subject"] = subj_df["subject"].apply(lambda k: subject_names.get(k, k))
                    st.dataframe(subj_df, use_container_width=True)
                display_subjects = [subject_names[k] for k in SUBJECT_KEYS]
                selected_display = st.selectbox("Select Subject", display_subjects)
                inv_map = {v: k for k, v in subject_names.items()}
                subject_key = inv_map[selected_display]
                existing = get_subjects_for_student(uni)
                existing_row = existing[existing["subject"] == subject_key]
                if not existing_row.empty:
                    existing_row = existing_row.iloc[0]
                    default_year = float(existing_row["year"]) if pd.notna(existing_row["year"]) else 0.0
                    default_mid = float(existing_row["mid"]) if pd.notna(existing_row["mid"]) else 0.0
                    default_final = float(existing_row["final"]) if pd.notna(existing_row["final"]) else 0.0
                else:
                    default_year = default_mid = default_final = 0.0
                y_val = st.number_input("Year Work (out of 30)", value=default_year, min_value=0.0, max_value=float(DEFAULT_YEAR_MAX), step=0.5)
                m_val = st.number_input("Midterm (out of 30)", value=default_mid, min_value=0.0, max_value=float(DEFAULT_MID_MAX), step=0.5)
                f_val = st.number_input("Final (out of 40)", value=default_final, min_value=0.0, max_value=float(DEFAULT_FINAL_MAX), step=0.5)
                if st.button("Save Grade"):
                    if y_val > DEFAULT_YEAR_MAX or m_val > DEFAULT_MID_MAX or f_val > DEFAULT_FINAL_MAX:
                        st.error("One of the grades exceeds the maximum allowed")
                    else:
                        pct, letter = upsert_subject_grade(uni, subject_key, y_val, m_val, f_val)
                        st.success(f"Saved — {selected_display}: {pct}% — {letter}")
                        safe_rerun()
                if st.button("Clear Grade"):
                    clear_subject_grade(uni, subject_key)
                    st.success("Grade cleared")
                    safe_rerun()

with tab_account:
    st.write(f"Logged in as: {st.session_state['user_email']}")
    if st.button("Logout"):
        logout()
