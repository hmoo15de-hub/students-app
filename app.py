# app.py
import sqlite3
import streamlit as st
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from io import BytesIO
from datetime import datetime
import time
import os

DB = "students_web.db"

# ---------- DB helpers and migration ----------
def get_conn():
    return sqlite3.connect(DB, check_same_thread=False)

def ensure_db_and_migrate():
    """Create table if missing and ensure 'active' column exists.
       Use 'uni' as primary key (no numeric id column)."""
    if not os.path.exists(DB):
        open(DB, "a").close()
    with get_conn() as conn:
        cur = conn.cursor()
        
        cur.execute('''
        CREATE TABLE IF NOT EXISTS students (
            name TEXT,
            uni TEXT PRIMARY KEY,
            year REAL,
            mid REAL,
            final REAL,
            percent REAL,
            letter TEXT,
            active INTEGER DEFAULT 1
        )
        ''')
        conn.commit()
        try:
            cur.execute("UPDATE students SET active=1 WHERE active IS NULL")
            conn.commit()
        except Exception:
            pass

def safe_rerun():
    """Try to rerun app; if not available, change query param to force rerun."""
    try:
        st.experimental_rerun()
    except Exception:
        try:
            st.experimental_set_query_params(_refresh=int(time.time()))
        except Exception:
            st.info("Refresh the page to see the changes.")

DEFAULT_YEAR_MAX = 30.0
DEFAULT_MID_MAX  = 30.0
DEFAULT_FINAL_MAX= 40.0
W_YEAR, W_MID, W_FINAL = 0.30, 0.30, 0.40

def compute_percent_from_defaults(y, m, f):
    try:
        y_pct = (float(y) / DEFAULT_YEAR_MAX) * 100 if y is not None else 0
    except:
        y_pct = 0
    try:
        m_pct = (float(m) / DEFAULT_MID_MAX) * 100 if m is not None else 0
    except:
        m_pct = 0
    try:
        f_pct = (float(f) / DEFAULT_FINAL_MAX) * 100 if f is not None else 0
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

def add_student(name, uni, year=None, mid=None, final=None):
    pct = None
    letter = None
    try:
        if year is not None or mid is not None or final is not None:
            pct = compute_percent_from_defaults(year or 0, mid or 0, final or 0)
            letter = percent_to_letter(pct)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO students (name, uni, year, mid, final, percent, letter, active) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                (name, uni, year, mid, final, pct, letter)
            )
            conn.commit()
        return True, None
    except sqlite3.IntegrityError:
        return False, "University number already exists"
    except Exception as e:
        return False, str(e)

def list_students():
    with get_conn() as conn:
        df = pd.read_sql_query("SELECT name, uni, year, mid, final, percent, letter, active FROM students WHERE active=1 ORDER BY uni", conn)
    return df

def update_grades(uni, year, mid, final, percent, letter):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE students SET year=?, mid=?, final=?, percent=?, letter=? WHERE uni=?",
            (year, mid, final, percent, letter, uni)
        )
        conn.commit()

def update_student_info(old_uni, new_name, new_uni):
    try:
        with get_conn() as conn:
            cur = conn.cursor()
    
            cur.execute("UPDATE students SET name=?, uni=? WHERE uni=?", (new_name, new_uni, old_uni))
            conn.commit()
        return True, None
    except sqlite3.IntegrityError:
        return False, "University number already exists"
    except Exception as e:
        return False, str(e)

def soft_delete_student(uni):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE students SET active=0 WHERE uni=?", (uni,))
        conn.commit()

def clear_grades(uni):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE students SET year=NULL, mid=NULL, final=NULL, percent=NULL, letter=NULL WHERE uni=?",
            (uni,)
        )
        conn.commit()

def hard_delete_student(uni):
    """Permanently delete a student row (no numeric id to reset)."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM students WHERE uni = ?", (uni,))
        conn.commit()


def generate_pdf(students_df):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 40
    y = height - margin
    c.setFont("Helvetica-Bold", 14)
    c.drawString(margin, y, "Student Grades Report")
    c.setFont("Helvetica", 10)
    y -= 20
    c.drawString(margin, y, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    y -= 30
    display_uni_label = "University number"
    cols = ["Name", display_uni_label, "Year", "Mid", "Final", "Percent", "Grade"]
    col_x = [margin, margin+180, margin+340, margin+400, margin+460, margin+520, margin+580]
    c.setFont("Helvetica-Bold", 10)
    for i, h in enumerate(cols):
        c.drawString(col_x[i], y, h)
    y -= 14
    c.setFont("Helvetica", 10)
    for _, row in students_df.iterrows():
        if y < 60:
            c.showPage()
            y = height - margin
            c.setFont("Helvetica-Bold", 10)
            for i, h in enumerate(cols):
                c.drawString(col_x[i], y, h)
            y -= 14
            c.setFont("Helvetica", 10)
        vals = [
            str(row['name']) if not pd.isna(row['name']) else '',
            str(row['uni']) if not pd.isna(row['uni']) else '',
            '' if pd.isna(row['year']) else str(row['year']),
            '' if pd.isna(row['mid']) else str(row['mid']),
            '' if pd.isna(row['final']) else str(row['final']),
            '' if pd.isna(row['percent']) else str(row['percent']),
            '' if pd.isna(row['letter']) else str(row['letter'])
        ]
        for i, v in enumerate(vals):
            c.drawString(col_x[i], y, v)
        y -= 14
    c.save()
    buffer.seek(0)
    return buffer


st.set_page_config(page_title="سجل الطلاب", layout="wide")
st.title("سجل الطلاب")


ensure_db_and_migrate()


if "_db_mtime" not in st.session_state:
    try:
        st.session_state["_db_mtime"] = os.path.getmtime(DB)
    except Exception:
        st.session_state["_db_mtime"] = 0.0

# Check DB mtime and rerun if changed
try:
    current_mtime = os.path.getmtime(DB)
except Exception:
    current_mtime = st.session_state.get("_db_mtime", 0.0)


if current_mtime != st.session_state.get("_db_mtime", 0.0):
    st.session_state["_db_mtime"] = current_mtime
    
    try:
        st.experimental_rerun()
    except Exception:
        
        try:
            st.experimental_set_query_params(_refresh=int(time.time()))
        except Exception:
            pass


with st.sidebar:
    st.header("Add student (with optional scores)")
    name = st.text_input("Name")
    uni = st.text_input("University number")
    st.markdown("**Optional: enter scores now**")
    y_in = st.number_input("Year work (points)", value=0.0, min_value=0.0, step=0.5, format="%.1f")
    m_in = st.number_input("Midterm (points)", value=0.0, min_value=0.0, step=0.5, format="%.1f")
    f_in = st.number_input("Final (points)", value=0.0, min_value=0.0, step=0.5, format="%.1f")
    use_scores = st.checkbox("Save these scores with the student", value=False)
    if st.button("Add"):
        if name.strip() and uni.strip():
            year_val = y_in if use_scores else None
            mid_val = m_in if use_scores else None
            final_val = f_in if use_scores else None
            ok, err = add_student(name.strip(), uni.strip(), year_val, mid_val, final_val)
            if ok:
                st.success("Student added")
                
                try:
                    st.session_state["_db_mtime"] = os.path.getmtime(DB)
                except Exception:
                    pass
                safe_rerun()
            else:
                st.error(err or "Failed to add student")
        else:
            st.error("Enter name and university number")


st.subheader("Students list")
df = list_students()


display_uni_label = "University number"
df_display = df.rename(columns={"uni": display_uni_label})
st.dataframe(df_display, use_container_width=True)


if not df_display.empty:
    csv = df_display.to_csv(index=False).encode('utf-8')
    st.download_button("Download CSV", data=csv, file_name="students.csv", mime="text/csv")


st.markdown("### Select student to edit scores or manage record")
students = df[['uni','name']].fillna('').astype(str)
options = students.apply(lambda r: f"{r['uni']} — {r['name']}", axis=1).tolist()
selected_opt = st.selectbox("Select student", [""] + options, key="student_select")

if selected_opt:
    selected_uni = selected_opt.split(" — ")[0]
    st.session_state['selected_uni'] = selected_uni


if 'selected_uni' in st.session_state:
    uni = st.session_state['selected_uni']
    student_row = df[df['uni'] == uni]
    if not student_row.empty:
        student_row = student_row.iloc[0]
        st.markdown(f"**Selected:** {student_row['name']} ({student_row['uni']})")

        
        st.markdown("#### Edit student info")
        new_name = st.text_input("Edit name", value=student_row['name'], key=f"edit_name_{uni}")
        new_uni = st.text_input("Edit university number", value=student_row['uni'], key=f"edit_uni_{uni}")
        if st.button("Save student info", key=f"save_info_{uni}"):
            if not new_name.strip() or not new_uni.strip():
                st.error("Name and university number cannot be empty")
            else:
                ok, err = update_student_info(uni, new_name.strip(), new_uni.strip())
                if ok:
                    st.success("Student info updated")
                    
                    try:
                        st.session_state["_db_mtime"] = os.path.getmtime(DB)
                    except Exception:
                        pass
                    
                    st.session_state['selected_uni'] = new_uni.strip()
                    safe_rerun()
                else:
                    st.error(err or "Failed to update student info")

        
        st.markdown("#### Delete student")
        if 'confirm_delete' not in st.session_state:
            st.session_state['confirm_delete'] = None
        if st.button("Delete student (permanent)", key=f"del_btn_{uni}"):
            st.session_state['confirm_delete'] = uni
        if st.session_state.get('confirm_delete') == uni:
            st.warning("Are you sure you want to permanently delete this student? This action cannot be undone.")
            cdel1, cdel2 = st.columns(2)
            with cdel1:
                if st.button("Confirm delete", key=f"confirm_del_{uni}"):
                    hard_delete_student(uni)
                    st.success("Student permanently deleted")
                    
                    try:
                        st.session_state["_db_mtime"] = os.path.getmtime(DB)
                    except Exception:
                        pass
                    st.session_state['confirm_delete'] = None
                    if 'selected_uni' in st.session_state:
                        del st.session_state['selected_uni']
                    safe_rerun()
            with cdel2:
                if st.button("Cancel delete", key=f"cancel_del_{uni}"):
                    st.session_state['confirm_delete'] = None
                    st.info("Delete cancelled")

        st.markdown("---")
        
        st.markdown("#### Edit scores")
        y_val = st.number_input("Year work (points)", value=0.0 if pd.isna(student_row['year']) else float(student_row['year']),
                                min_value=0.0, max_value=float(DEFAULT_YEAR_MAX), step=0.5, key=f"y_val_{uni}")
        m_val = st.number_input("Midterm (points)", value=0.0 if pd.isna(student_row['mid']) else float(student_row['mid']),
                                min_value=0.0, max_value=float(DEFAULT_MID_MAX), step=0.5, key=f"m_val_{uni}")
        f_val = st.number_input("Final (points)", value=0.0 if pd.isna(student_row['final']) else float(student_row['final']),
                                min_value=0.0, max_value=float(DEFAULT_FINAL_MAX), step=0.5, key=f"f_val_{uni}")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Save scores", key=f"save_scores_{uni}"):
                if y_val > DEFAULT_YEAR_MAX or m_val > DEFAULT_MID_MAX or f_val > DEFAULT_FINAL_MAX:
                    st.error("One of the scores exceeds its max allowed value")
                else:
                    pct = compute_percent_from_defaults(y_val, m_val, f_val)
                    if pct > 100:
                        st.error(f"Calculated percent {pct}% exceeds 100 — check inputs")
                    else:
                        letter = percent_to_letter(pct)
                        update_grades(uni, y_val, m_val, f_val, pct, letter)
                        st.success(f"Saved — Percent: {pct}% — Grade: {letter}")
                        
                        try:
                            st.session_state["_db_mtime"] = os.path.getmtime(DB)
                        except Exception:
                            pass
                        safe_rerun()
        with c2:
            if st.button("Clear scores", key=f"clear_scores_{uni}"):
                clear_grades(uni)
                st.success("Scores cleared")
                try:
                    st.session_state["_db_mtime"] = os.path.getmtime(DB)
                except Exception:
                    pass
                safe_rerun()
    else:
        st.warning("Selected student not found")
else:
    st.info("Select a student from the dropdown to edit, delete, or change scores")


st.markdown("---")
st.header("Export")
st.write("You can export the current table to a PDF report.")
if st.button("Generate PDF"):
    df2 = list_students()
    if df2.empty:
        st.warning("No students to export")
    else:
        pdf_buffer = generate_pdf(df2)
        st.download_button(label="Download PDF", data=pdf_buffer, file_name="students_report.pdf", mime="application/pdf")
