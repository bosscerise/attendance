import streamlit as st
from st_login_form import login_form
from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app

# Firebase credentials
firebase_credentials = {
    "type": st.secrets["FIREBASE_CREDENTIALS"]["type"],
    "project_id": st.secrets["FIREBASE_CREDENTIALS"]["project_id"],
    "private_key_id": st.secrets["FIREBASE_CREDENTIALS"]["private_key_id"],
    "private_key": st.secrets["FIREBASE_CREDENTIALS"]["private_key"],
    "client_email": st.secrets["FIREBASE_CREDENTIALS"]["client_email"],
    "client_id": st.secrets["FIREBASE_CREDENTIALS"]["client_id"],
    "auth_uri": st.secrets["FIREBASE_CREDENTIALS"]["auth_uri"],
    "token_uri": st.secrets["FIREBASE_CREDENTIALS"]["token_uri"],
    "auth_provider_x509_cert_url": st.secrets["FIREBASE_CREDENTIALS"]["auth_provider_x509_cert_url"],
    "client_x509_cert_url": st.secrets["FIREBASE_CREDENTIALS"]["client_x509_cert_url"]
}

# Initialize Firebase
def init_firebase():
    cred = credentials.Certificate(firebase_credentials)
    try:
        firebase_admin.get_app()
    except ValueError:
        initialize_app(cred)
    return firestore.client()

db = init_firebase()

# Authentication check
def authenticate(username, password):
    return username == "admin" and password == "password"

# Insert attendance to Firestore
def insert_attendance(employee_name, check_type, date, time):
    try:
        doc_id = f"{employee_name}_{date}_{check_type}_{time}"
        db.collection('attendance').document(doc_id).set({
            'employee_name': employee_name,
            'check_type': check_type,
            'date': date,
            'time': time
        })
        st.success(f"Attendance recorded for {employee_name}: {check_type} at {time}")
    except Exception as e:
        st.error(f"An error occurred while inserting attendance: {e}")

# Get last check event for an employee on a given date
def get_last_check(employee_name, date, check_type):
    records = db.collection('attendance') \
                .where('employee_name', '==', employee_name) \
                .where('date', '==', date) \
                .where('check_type', '==', check_type) \
                .order_by('time', direction=firestore.Query.DESCENDING) \
                .limit(1) \
                .stream()
    return next(records, None)

# Process check-in/out event
def process_check(barcode):
    now = datetime.now()
    date = now.strftime("%Y-%m-%d")
    time = now.strftime("%H:%M:%S")

    # Find employee by barcode
    employee_record = db.collection('employees').where('barcode', '==', barcode).get()
    if employee_record:
        employee_name = employee_record[0].to_dict()['employee_name']
    else:
        st.warning("Employee not found. Please scan again or register a new employee.")
        return

    # Determine check type
    last_check_in = get_last_check(employee_name, date, "Check In")
    if last_check_in is None:
        check_type = "Check In"
    else:
        last_check_out = get_last_check(employee_name, date, "Check Out")
        check_type = "Check Out" if last_check_out is None or last_check_out.to_dict()['time'] < last_check_in.to_dict()['time'] else "Check In"

    # Insert attendance and update work time if checking out
    insert_attendance(employee_name, check_type, date, time)
    if check_type == "Check Out":
        total_work_time = calculate_total_work_time(employee_name, date)
        update_work_times(employee_name, date)

def get_last_check(employee_name, date, check_type):
    records = db.collection('attendance').where('employee_name', '==', employee_name).where('date', '==', date).where('check_type', '==', check_type).order_by('time', direction=firestore.Query.DESCENDING).limit(1).stream()
    return next(records, None)

def calculate_total_work_time(employee_name, date):
    check_ins = db.collection('attendance').where('employee_name', '==', employee_name).where('date', '==', date).where('check_type', '==', 'Check In').stream()
    check_outs = db.collection('attendance').where('employee_name', '==', employee_name).where('date', '==', date).where('check_type', '==', 'Check Out').stream()

    total_seconds = 0
    for check_in, check_out in zip(check_ins, check_outs):
        check_in_time = datetime.strptime(check_in.to_dict()['time'], "%H:%M:%S")
        check_out_time = datetime.strptime(check_out.to_dict()['time'], "%H:%M:%S")
        total_seconds += (check_out_time - check_in_time).total_seconds()

    if total_seconds <= 0:
        return "0:00:00"
    else:
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        # Format the output string
        return f"{hours:02d}:{minutes:02d}:{seconds:05.2f}"

def update_work_times(employee_name, date):
    total_work_time = calculate_total_work_time(employee_name, date)
    try:
        doc_ref = db.collection('work_times').document(f"{employee_name}_{date}")
        doc_ref.set({
            'employee_name': employee_name,
            'date': date,
            'total_work_time': str(total_work_time)  # Convert to string
        }, merge=True)
    except Exception as e:
        st.error(f"An error occurred while updating work times: {e}")


# Register employee in Firestore
def register_employee(employee_name, barcode):
    try:
        db.collection('employees').add({
            'employee_name': employee_name,
            'barcode': barcode
        })
        st.success(f"Employee '{employee_name}' registered successfully!")
    except Exception as e:
        st.error(f"An error occurred while registering employee: {e}")

# Streamlit app layout
st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", ["Login", "Check In/Out", "View Total Hours Worked", "Register New Employee"])

if page == "Login":
    st.title("Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    
    if st.button("Login"):
        if authenticate(username, password):
            st.session_state['authenticated'] = True
            st.success("Logged in successfully!")
        else:
            st.error("Invalid username or password")

if st.session_state.get('authenticated'):
    if page == "Check In/Out":
        st.title("Employee Attendance System with Barcode Scanner")
        barcode = st.text_input("Scan Barcode")
        if st.button("Submit") and barcode:
            process_check(barcode)
            st.session_state.barcode = ""

    elif page == "View Total Hours Worked":
        st.title("Total Hours Worked")
        employee_records = db.collection('employees').get()
        employee_names = [record.to_dict().get('employee_name') for record in employee_records]

        if len(employee_names) == 0:
            st.warning("No employees found. Please add an employee to start tracking attendance.")
        else:
            selected_employee = st.selectbox("Select Employee", employee_names)
            start_date = st.date_input("Start Date", value=datetime.now() - timedelta(days=30))
            end_date = st.date_input("End Date", value=datetime.now())

            if start_date > end_date:
                st.error("Start date must be before or equal to end date.")
            else:
                if st.button("Calculate Total Hours"):
                    total_hours = calculate_total_work_time(selected_employee, start_date.strftime("%Y-%m-%d"))
                    st.success(f"Total hours worked by {selected_employee} from {start_date} to {end_date}: {total_hours}")


    elif page == "Register New Employee":
        st.title("Register New Employee")
        employee_name = st.text_input("Employee Name")
        barcode = st.text_input("Barcode")
        if st.button("Register"):
            register_employee(employee_name, barcode)
else:
    st.warning("Please log in to access these features.")

