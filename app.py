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

# Hardcoded authentication (simple approach)
USERNAME = "admin"
PASSWORD = "password"

# Authentication check
def authenticate(username, password):
    return username == USERNAME and password == PASSWORD

# Insert attendance to Firestore
def insert_attendance(employee_name, check_type, date, time):
    try:
        db.collection('attendance').add({
            'employee_name': employee_name,
            'check_type': check_type,
            'date': date,
            'time': time
        })
        st.success(f"Attendance for {employee_name} recorded: {check_type} at {time}")
    except Exception as e:
        st.error(f"An error occurred while inserting attendance: {e}")

# Calculate total work time
def calculate_total_work_time(employee_name, date):
    records = db.collection('attendance') \
                .where('employee_name', '==', employee_name) \
                .where('date', '==', date) \
                .stream()

    total_seconds = 0
    check_in_time = None

    for record in records:
        data = record.to_dict()
        time_obj = datetime.strptime(data['time'], "%H:%M:%S")

        if data['check_type'] == 'Check In':
            check_in_time = time_obj
        elif data['check_type'] == 'Check Out' and check_in_time:
            time_diff = time_obj - check_in_time
            total_seconds += time_diff.total_seconds()
            check_in_time = None

    return str(timedelta(seconds=total_seconds)) if total_seconds > 0 else "0:00:00"

# Update work times in Firestore
def update_work_times(employee_name, date):
    total_work_time = calculate_total_work_time(employee_name, date)
    try:
        db.collection('work_times').document(f"{employee_name}_{date}").set({
            'employee_name': employee_name,
            'date': date,
            'total_work_time': total_work_time
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

# Get last check-in from Firestore
def get_last_check_in(employee_name, date):
    records = db.collection('attendance') \
                   .where('employee_name', '==', employee_name) \
                   .where('date', '==', date) \
                   .where('check_type', '==', 'Check In') \
                   .order_by('time', direction=firestore.Query.DESCENDING) \
                   .limit(1) \
                   .stream()

    for record in records:
        return record.to_dict()['time']
    return None

# Process check (Check In/Out)
def process_check(barcode):
    try:
        employee_ref = db.collection('employees').document(barcode)
        employee_doc = employee_ref.get()
        
        if not employee_doc.exists:
            st.error("Employee not found")
            return
        
        employee_data = employee_doc.to_dict()
        employee_name = employee_data['employee_name']
        date = datetime.now().strftime("%Y-%m-%d")
        time = datetime.now().strftime("%H:%M:%S")

        last_check_in_time = get_last_check_in(employee_name, date)

        if last_check_in_time is None:
            check_type = "Check In"
        else:
            check_outs = db.collection('attendance') \
                           .where('employee_name', '==', employee_name) \
                           .where('date', '==', date) \
                           .where('check_type', '==', 'Check Out') \
                           .where('time', '>', last_check_in_time) \
                           .stream()
            
            if sum(1 for _ in check_outs) == 0:
                check_type = "Check Out"
            else:
                check_type = "Check In"

        insert_attendance(employee_name, check_type, date, time)

        if check_type == "Check In":
            st.success(f"{employee_name} checked in at {time}")
        elif check_type == "Check Out":
            st.success(f"{employee_name} checked out at {time}")
            total_work_time = calculate_total_work_time(employee_name, date)
            update_work_times(employee_name, date)

            daily_summary = f"""
            <h3>Daily Summary</h3>
            <p>Employee: {employee_name}</p>
            <p>Date: {date}</p>
            <p>Total Work Time: {total_work_time}</p>
            """
            st.markdown(daily_summary, unsafe_allow_html=True)
    except Exception as e:
        st.error(f"An error occurred: {str(e)}")

# Streamlit app layout
st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", ["Login", "Check In/Out", "View Total Hours Worked", "Register New Employee"])

# Authentication
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

# If authenticated, show main app
if st.session_state.get('authenticated'):
    if page == "Check In/Out":
        st.title("Employee Attendance System with Barcode Scanner")
        barcode = st.text_input("Scan Barcode")

        if st.button("Submit") and barcode:
            process_check(barcode)
            st.session_streamlit.barcode = ""

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

# Main app logic
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

# Error handling for database operations
try:
    # Your database operation code here
except Exception as e:
    st.error(f"An error occurred: {str(e)}")

