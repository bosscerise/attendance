import streamlit as st
from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
from google.cloud.firestore_v1.base_query import FieldFilter
import time
import pytz
import pandas as pd

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
    now = now + timedelta(hours=1)
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
    now = now + timedelta(hours=1)
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



# New function to get employee timeline
def get_employee_timeline(employee_name, start_date, end_date):
    timeline = []
    date_range = pd.date_range(start=start_date, end=end_date)
    
    for date in date_range:
        date_str = date.strftime("%Y-%m-%d")
        checks = (db.collection('attendance')
                  .where(filter=FieldFilter('employee_name', '==', employee_name))
                  .where(filter=FieldFilter('date', '==', date_str))
                  .order_by('time')
                  .stream())
        
        check_in_time = None
        for check in checks:
            check_data = check.to_dict()
            if check_data['check_type'] == 'Check In':
                check_in_time = datetime.strptime(f"{date_str} {check_data['time']}", "%Y-%m-%d %H:%M:%S")
            elif check_data['check_type'] == 'Check Out' and check_in_time:
                check_out_time = datetime.strptime(f"{date_str} {check_data['time']}", "%Y-%m-%d %H:%M:%S")
                duration = (check_out_time - check_in_time).total_seconds() / 3600  # Duration in hours
                timeline.append({
                    'date': date_str,
                    'start_time': check_in_time.strftime("%H:%M:%S"),
                    'end_time': check_out_time.strftime("%H:%M:%S"),
                    'duration': duration
                })
                check_in_time = None
    
    return timeline


# New function to update attendance record
def update_attendance(doc_id, new_time):
    try:
        doc_ref = db.collection('attendance').document(doc_id)
        doc_ref.update({'time': new_time})
        st.success("Attendance record updated successfully!")
    except Exception as e:
        st.error(f"An error occurred while updating the attendance record: {e}")

# New function to delete attendance record
def delete_attendance(doc_id):
    try:
        db.collection('attendance').document(doc_id).delete()
        st.success("Attendance record deleted successfully!")
    except Exception as e:
        st.error(f"An error occurred while deleting the attendance record: {e}")



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
                st.success("Logged in successfully!, rabi y3awnk")
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
            time.sleep(5)
            st.rerun()

    elif page == "Current Attendance":
        st.title("Current Attendance Status")
        current_status = get_current_attendance()
        realtime = datetime.now() + timedelta(hours=1)
        
        st.write("Last updated:", realtime.strftime("%Y-%m-%d %H:%M:%S"))
        
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


    elif page == "Employee Timeline":
        st.title("Employee Timeline and Attendance Management")

        # Employee selection
        employees = [doc.to_dict()['employee_name'] for doc in db.collection('employees').stream()]
        selected_employee = st.selectbox("Select Employee", employees)

        # Date range selection
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date", value=datetime.now() - timedelta(days=7))
        with col2:
            end_date = st.date_input("End Date", value=datetime.now())

        if start_date <= end_date:
            # Fetch timeline data
            timeline_data = get_employee_timeline(selected_employee, start_date, end_date)

            if timeline_data:
                # Create a DataFrame for the timeline
                df = pd.DataFrame(timeline_data)

                # Create a bar chart using Streamlit
                st.subheader(f"Work Sessions for {selected_employee}")
                chart = st.bar_chart(
                    df.set_index('date')['duration'],
                    use_container_width=True,
                    height=400
                )

                # Display total hours worked
                total_hours = df['duration'].sum()
                st.metric("Total Hours Worked", f"{total_hours:.2f} hours")

                # Display attendance records with CRUD operations
                st.subheader("Attendance Records")
                for record in timeline_data:
                    with st.expander(f"{record['date']} - {record['start_time']} to {record['end_time']} ({record['duration']:.2f} hours)"):
                        doc_id = f"{selected_employee}_{record['date']}_{record['start_time']}"
                        
                        # Edit start time
                        new_start_time = st.time_input("Edit start time", datetime.strptime(record['start_time'], "%H:%M:%S").time())
                        
                        # Edit end time
                        new_end_time = st.time_input("Edit end time", datetime.strptime(record['end_time'], "%H:%M:%S").time())
                        
                        if st.button("Update", key=f"update_{doc_id}"):
                            update_attendance(doc_id, new_start_time.strftime("%H:%M:%S"))
                            update_attendance(f"{selected_employee}_{record['date']}_{record['end_time']}", new_end_time.strftime("%H:%M:%S"))
                            st.success("Attendance record updated successfully!")
                            st.rerun()
                        
                        # Delete record
                        if st.button("Delete", key=f"delete_{doc_id}"):
                            delete_attendance(doc_id)
                            delete_attendance(f"{selected_employee}_{record['date']}_{record['end_time']}")
                            st.success("Attendance record deleted successfully!")
                            st.rerun()

                # Add new attendance record
                st.subheader("Add New Attendance Record")
                new_date = st.date_input("Date", value=datetime.now())
                new_start_time = st.time_input("Start Time", value=datetime.now().time())
                new_end_time = st.time_input("End Time", value=(datetime.now() + timedelta(hours=8)).time())
                if st.button("Add Record"):
                    insert_attendance(selected_employee, "Check In", new_date.strftime("%Y-%m-%d"), new_start_time.strftime("%H:%M:%S"))
                    insert_attendance(selected_employee, "Check Out", new_date.strftime("%Y-%m-%d"), new_end_time.strftime("%H:%M:%S"))
                    st.success("New attendance record added successfully!")
                    st.rerun()

            else:
                st.info("No records found for the selected date range.")
        else:
            st.error("Start date must be before or equal to end date.")



    elif page == "Register New Employee":
        st.title("Register New Employee")
        with st.form("register_employee"):
            employee_name = st.text_input("Employee Name")
            barcode = st.text_input("Barcode")
            submit_button = st.form_submit_button("Register")

            if submit_button and employee_name and barcode:
                register_employee(employee_name, barcode)
