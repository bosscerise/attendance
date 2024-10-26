import streamlit as st
from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
from google.cloud.firestore_v1.base_query import FieldFilter
import time
import pytz

# Firebase initialization
def init_firebase():
    if not firebase_admin._apps:
        firebase_cred = credentials.Certificate({
            "type": st.secrets["FIREBASE_CREDENTIALS"]["type"],
            "project_id": st.secrets["FIREBASE_CREDENTIALS"]["project_id"],
            "private_key_id": st.secrets["FIREBASE_CREDENTIALS"]["private_key_id"],
            "private_key": st.secrets["FIREBASE_CREDENTIALS"]["private_key"],
            "client_email": st.secrets["FIREBASE_CREDENTIALS"]["client_email"],
            "client_id": st.secrets["FIREBASE_CREDENTIALS"]["client_id"],
            "auth_uri": st.secrets["FIREBASE_CREDENTIALS"]["auth_uri"],
            "token_uri": st.secrets["FIREBASE_CREDENTIALS"]["token_uri"],
            "auth_provider_x509_cert_url": st.secrets["FIREBASE_CREDENTIALS"]["auth_provider_x509_cert_url"],
            "client_x509_cert_url": st.secrets["FIREBASE_CREDENTIALS"]["client_x509_cert_url"],
        })
        firebase_admin.initialize_app(firebase_cred)
    return firestore.client()

# Initialize the Firestore database
db = init_firebase()

# Authentication
def authenticate(username, password):
    return username == st.secrets["ADMIN_USERNAME"] and password == st.secrets["ADMIN_PASSWORD"]

def authenticatend(spusername, sppassword):
    return spusername == st.secrets["SUPER_USERNAME"] and sppassword == st.secrets["SUPER_PASSWORD"]

# Firestore operations
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

def get_last_check(employee_name, date, check_type):
    records = db.collection('attendance').where(filter=FieldFilter('employee_name', '==', employee_name)).where(filter=FieldFilter('date', '==', date)).where(filter=FieldFilter('check_type', '==', check_type)).order_by('time', direction=firestore.Query.DESCENDING).limit(1).stream()
    return next(records, None)

def process_check(barcode):
    now = datetime.now()
    date = now.strftime("%Y-%m-%d")
    time = now.strftime("%H:%M:%S")

    employee_record = next(db.collection('employees').where('barcode', '==', barcode).limit(1).stream(), None)
    if not employee_record:
        st.warning("Employee not found. Please scan again or register a new employee.")
        return

    employee_name = employee_record.to_dict()['employee_name']
    last_check_in = get_last_check(employee_name, date, "Check In")
    last_check_out = get_last_check(employee_name, date, "Check Out")

    check_type = "Check In" if not last_check_in or (last_check_out and last_check_out.to_dict()['time'] > last_check_in.to_dict()['time']) else "Check Out"

    insert_attendance(employee_name, check_type, date, time)
    if check_type == "Check Out":
        update_work_times(employee_name, date)

def calculate_total_work_time(employee_name, start_date, end_date):
    total_seconds = 0
    current_date = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    while current_date <= end:
        date_str = current_date.strftime("%Y-%m-%d")
        check_ins = db.collection('attendance').where(filter=FieldFilter('employee_name', '==', employee_name)).where(filter=FieldFilter('date', '==', date_str)).where(filter=FieldFilter('check_type', '==', 'Check In')).stream()
        check_outs = db.collection('attendance').where(filter=FieldFilter('employee_name', '==', employee_name)).where(filter=FieldFilter('date', '==', date_str)).where(filter=FieldFilter('check_type', '==', 'Check Out')).stream()

        for check_in, check_out in zip(check_ins, check_outs):
            check_in_time = datetime.strptime(check_in.to_dict()['time'], "%H:%M:%S")
            check_out_time = datetime.strptime(check_out.to_dict()['time'], "%H:%M:%S")
            total_seconds += (check_out_time - check_in_time).total_seconds()

        current_date += timedelta(days=1)

    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"

def update_work_times(employee_name, date):
    total_work_time = calculate_total_work_time(employee_name, date, date)
    try:
        doc_ref = db.collection('total_work_times').document(f"{employee_name}_{date}")
        doc_ref.set({
            'employee_name': employee_name,
            'date': date,
            'total_work_time': total_work_time
        }, merge=True)
    except Exception as e:
        st.error(f"An error occurred while updating work times: {e}")

def register_employee(employee_name, barcode):
    try:
        existing_employee = db.collection('employees').where('barcode', '==', barcode).limit(1).get()
        if existing_employee:
            st.error("This barcode is already registered to another employee.")
            return

        db.collection('employees').add({
            'employee_name': employee_name,
            'barcode': barcode
        })
        st.success(f"Employee '{employee_name}' registered successfully!")
    except Exception as e:
        st.error(f"An error occurred while registering employee: {e}")

# New functions for additional pages
def get_current_attendance():
    now = datetime.now()
    date = now.strftime("%Y-%m-%d")
    
    all_employees = db.collection('employees').stream()
    current_status = {}

    for employee in all_employees:
        employee_name = employee.to_dict()['employee_name']
        last_check_in = get_last_check(employee_name, date, "Check In")
        last_check_out = get_last_check(employee_name, date, "Check Out")

        if last_check_in and (not last_check_out or last_check_in.to_dict()['time'] > last_check_out.to_dict()['time']):
            current_status[employee_name] = "Checked In"
        else:
            current_status[employee_name] = "Checked Out"

    return current_status

def get_employee_timeline(employee_name, date):
    timeline = []
    checks = (db.collection('attendance')
              .where(filter=FieldFilter('employee_name', '==', employee_name))
              .where(filter=FieldFilter('date', '==', date))
              .order_by('time', direction=firestore.Query.ASCENDING)
              .order_by(firestore.field_path.FieldPath.document_id(), direction=firestore.Query.ASCENDING)
              .stream())

    for check in checks:
        check_data = check.to_dict()
        timeline.append((check_data['time'], check_data['check_type']))

    return timeline

# Streamlit UI
st.set_page_config(page_title="Employee Attendance System", layout="wide")

st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", ["Login", "Check In/Out", "View Total Hours Worked", "Register New Employee", "Current Attendance", "Employee Timeline"])

if page == "Login":
    st.title("Login")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submit_button = st.form_submit_button("Login")

        if submit_button:
            if authenticate(username, password):
                st.session_state['authenticated'] = True
                st.success("Logged in successfully!")
            elif authenticatend(username, password):
                st.session_state['authenticatend'] = True
                st.success("Hi bachir ou kader :3 !")
            else:
                st.error("Invalid username or password")

if st.session_state.get('authenticated') or st.session_state.get('authenticatend'):
    if page == "Check In/Out":
        st.title("Employee Attendance System")
        barcode = st.text_input("Scan Barcode", key="barcode_input")
        if st.button("Submit") and barcode:
            process_check(barcode)
            time.sleep(2)
            st.rerun()

    elif page == "Current Attendance":
        st.title("Current Attendance Status")
        current_status = get_current_attendance()
        
        st.write("Last updated:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Checked In")
            for employee, status in current_status.items():
                if status == "Checked In":
                    st.write(employee)
        
        with col2:
            st.subheader("Checked Out")
            for employee, status in current_status.items():
                if status == "Checked Out":
                    st.write(employee)
        
        if st.button("Refresh"):
            st.rerun()

    elif page == "Employee Timeline":
        st.title("Employee Daily Timeline")
        
        employee_records = db.collection('employees').get()
        employee_names = [record.to_dict().get('employee_name') for record in employee_records]
        
        selected_employee = st.selectbox("Select Employee", employee_names)
        selected_date = st.date_input("Select Date", value=datetime.now())
        
        if st.button("Show Timeline"):
            timeline = get_employee_timeline(selected_employee, selected_date.strftime("%Y-%m-%d"))
            
            if timeline:
                st.subheader(f"Timeline for {selected_employee} on {selected_date}")
                for time, check_type in timeline:
                    st.write(f"{time} - {check_type}")
            else:
                st.info("No records found for the selected date.")

if st.session_state.get('authenticatend'):
    if page == "View Total Hours Worked":
        st.title("Total Hours Worked")
        employee_records = db.collection('employees').get()
        employee_names = [record.to_dict().get('employee_name') for record in employee_records]

        if not employee_names:
            st.warning("No employees found. Please add an employee to start tracking attendance.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                selected_employee = st.selectbox("Select Employee", employee_names)
                start_date = st.date_input("Start Date", value=datetime.now() - timedelta(days=30))
            with col2:
                end_date = st.date_input("End Date", value=datetime.now())

            if start_date > end_date:
                st.error("Start date must be before or equal to end date.")
            elif st.button("Calculate Total Hours"):
                total_hours = calculate_total_work_time(selected_employee, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
                st.success(f"Total hours worked by {selected_employee} from {start_date} to {end_date}: {total_hours}")

    elif page == "Register New Employee":
        st.title("Register New Employee")
        with st.form("register_employee"):
            employee_name = st.text_input("Employee Name")
            barcode = st.text_input("Barcode")
            submit_button = st.form_submit_button("Register")

            if submit_button and employee_name and barcode:
                register_employee(employee_name, barcode)
