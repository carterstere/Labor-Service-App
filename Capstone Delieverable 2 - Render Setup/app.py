# Import necessary libraries for web app, database, geolocation, and time handling
from flask import Flask, render_template, request, redirect, session
import mysql.connector
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from geopy.exc import GeocoderTimedOut
import time
from datetime import datetime

# Initialize geolocator (used to convert addresses into coordinates)
geolocator = Nominatim(user_agent="job_app")

# Create Flask application instance
app = Flask(__name__)
app.secret_key = "password"

# --- Database connection ---
# Connect to MySQL database where user data is stored
db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="password",
    database="user_storage"
)
cursor = db.cursor()

# --- Safe geocode function with retries ---
# This function attempts to convert an address into coordinates
# It retries multiple times in case of timeout errors
def do_geocode(address, retries=3, delay=1):
    for i in range(retries):
        try:
            # Attempt to geocode the address
            return geolocator.geocode(address)
        # If timeout occurs and retries are left, wait and retry
        except GeocoderTimedOut:
            if i < retries - 1:
                time.sleep(delay)
            else:
                # If all retries fail, return None
                return None

# ---------------- INDEX ----------------
# Route for the homepage (landing page)
@app.route('/')
def index():
    return render_template('index.html')

# ---------------- SIGNUP ----------------
# Handles both displaying signup page and processing signup form
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    # If form is submitted
    if request.method == 'POST':
        # Get user input from form
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        email = request.form['email']
        password = request.form['password']
        account_type = request.form['account_type']

        # Check if user already exists with this email
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        existing_user = cursor.fetchone()
        # If email already exists, show error
        if existing_user:
            return render_template("signup.html", error="Email already in use.")

        # Insert new user into database
        cursor.execute("""
            INSERT INTO users 
            (first_name, last_name, email, password, account_type, login_count)
            VALUES (%s,%s,%s,%s,%s,0)
        """, (first_name, last_name, email, password, account_type))
        # Save changes to database
        db.commit()
        # Redirect user to login page after successful signup
        return redirect("/login")

    # If GET request, just show signup page
    return render_template('signup.html')

# ---------------- LOGIN ----------------
# Handles login functionality
@app.route('/login', methods=['GET', 'POST'])
def login():
    # If login form is submitted
    if request.method == 'POST':
        # Get login credentials from form
        email = request.form['email']
        password = request.form['password']

        # Check if user exists with matching email and password
        cursor.execute(
            "SELECT * FROM users WHERE email=%s AND password=%s",
            (email, password)
        )
        user = cursor.fetchone()

        # If user is found (valid login)
        if user:
            # Store user email in session (keeps user logged in)
            session['user_email'] = email

            # Increment login count for this user
            cursor.execute(
                "UPDATE users SET login_count = login_count + 1 WHERE email=%s",
                (email,)
            )
            db.commit()

            # Retrieve updated user info
            cursor.execute("""
                SELECT login_count, street_address, city, state, zip_code, phone, user_experience_completed
                FROM users WHERE email=%s
            """, (email,))
            result = cursor.fetchone()

            # Extract values from query result
            login_count = result[0]
            # Check if any profile fields are missing
            profile_incomplete = not all(result[1:6])
            # Check if user has completed experience setup
            experience_done = result[6] == 1 if result[6] is not None else False

            # 1. Must finish profile first
            if profile_incomplete:
                return redirect("/setup_profile")

            # 2. Must finish experience second
            elif not experience_done:
                return redirect("/add_experience")

            # 3. Optional: first-time login can still force profile (safety net)
            elif login_count == 1:
                return redirect("/setup_profile")

            else:
                return redirect("/homepage")

        else:
            # Invalid login credentials give an error
            return render_template("login.html", error="Invalid email or password")

    # If GET request then show login page
    return render_template('login.html')

# ---------------- SETUP PROFILE ----------------
# Route to allow users to complete or update their profile information
@app.route('/setup_profile', methods=['GET', 'POST'])
def setup_profile():
    # Ensure user is logged in before accessing this page
    if 'user_email' not in session:
        return redirect("/login")

    # Get logged-in user's email from session
    email = session['user_email']

    # If the form is submitted
    if request.method == 'POST':
        # Collect address and contact information from form
        street = request.form['street_address']
        city = request.form['city']
        state = request.form['state']
        zip_code = request.form['zip_code']
        phone = request.form['phone']

        # Get birthdate input and initialize age
        birthdate = request.form['birthdate']
        age = None

        # Calculate age if birthdate is provided
        if birthdate:
            birthdate_obj = datetime.strptime(birthdate, "%Y-%m-%d")
            today = datetime.today()
            age = today.year - birthdate_obj.year - (
                (today.month, today.day) < (birthdate_obj.month, birthdate_obj.day)
            )

        # Combine full address into a single string for geocoding
        address = f"{street}, {city}, {state}, {zip_code}"
        location = do_geocode(address)

        # Attempt to get latitude and longitude from full address
        if location:
            # If full address works, store exact coordinates
            lat = location.latitude
            lon = location.longitude
        else:
            # Fallback: try geocoding just city/state/zip
            city_location = do_geocode(f"{city}, {state}, {zip_code}")
            if city_location:
                lat = city_location.latitude
                lon = city_location.longitude
            else:
                # If all geocoding fails, default to 0 (invalid placeholder)
                lat = 0
                lon = 0

        # Update user's profile information in the database
        cursor.execute("""
            UPDATE users
            SET street_address=%s, city=%s, state=%s, zip_code=%s, phone=%s,
                birthdate=%s, age=%s,
                latitude=%s, longitude=%s
            WHERE email=%s
        """, (street, city, state, zip_code, phone, birthdate, age, lat, lon, email))

        # Save changes to database
        db.commit()
        # Redirect user to experience setup after completing profile
        return redirect("/add_experience")

    # If GET request, fetch existing user data to pre-fill the form
    cursor.execute("""
        SELECT first_name, last_name, email, street_address, city, state, zip_code, phone, birthdate
        FROM users WHERE email=%s
    """, (email,))
    user = cursor.fetchone()

    # Render profile setup page with existing user data
    return render_template("setup_profile.html", user=user)

# ---------------- ADD EXPERIENCE ----------------
# Route for users to add their work experience and skills
@app.route('/add_experience', methods=['GET', 'POST'])
def add_experience():
    # Ensure user is logged in before accessing this page
    if 'user_email' not in session:
        return redirect("/login")

    # If the form is submitted
    if request.method == 'POST':
        # Get logged-in user's email
        email = session['user_email']

        # Insert user experience data into the user_experience table
        cursor.execute("""
            INSERT INTO user_experience (
                user_email,
                lawn_mowing, snow_removal, gardening,
                mulching, raking_leaves, power_washing,
                junk_removal, item_moving, car_washing,
                pool_cleaning, about
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            email,
            request.form['lawn_mowing'],
            request.form['snow_removal'],
            request.form['gardening'],
            request.form['mulching'],
            request.form['raking_leaves'],
            request.form['power_washing'],
            request.form['junk_removal'],
            request.form['item_moving'],
            request.form['car_washing'],
            request.form['pool_cleaning'],
            request.form['about']
        ))

        # Save experience data to the database
        db.commit()   

        # Mark that the user has completed the experience setup step
        cursor.execute("""
            UPDATE users
            SET user_experience_completed = 1
            WHERE email = %s
        """, (email,))
        # Save update to database
        db.commit()   

        # Redirect to homepage after completing onboarding
        return redirect("/homepage")

    # If GET request, display the experience form
    return render_template("add_experience.html")

# ---------------- PROFILE ----------------
# Route for viewing and updating user profile information
@app.route('/profile', methods=['GET', 'POST'])
def profile():
    # Ensure user is logged in
    if 'user_email' not in session:
        return redirect("/login")

    # Get current logged-in user's email
    current_email = session['user_email']

    # If the profile update form is submitted
    if request.method == 'POST':
        # Get the new email entered by the user
        new_email = request.form['email']

        # Check if the new email already exists in the database
        cursor.execute("SELECT * FROM users WHERE email=%s", (new_email,))
        existing = cursor.fetchone()

        # Prevent duplicate email unless it is the same as the current one
        if existing and new_email != current_email:
            return redirect("/profile")

        # Collect updated address and contact information
        street = request.form['street_address']
        city = request.form['city']
        state = request.form['state']
        zip_code = request.form['zip_code']
        phone = request.form['phone']

        # Combine address for geocoding
        address = f"{street}, {city}, {state}, {zip_code}"
        location = do_geocode(address)

         # Attempt to get coordinates from full address
        if location:
            lat = location.latitude
            lon = location.longitude
        else:
            # Fallback to city-level geocoding if full address fails
            city_location = do_geocode(f"{city}, {state}, {zip_code}")
            if city_location:
                lat = city_location.latitude
                lon = city_location.longitude
            else:
                # Default values if geocoding fails completely
                lat = 0
                lon = 0

        # Update user profile information in the database
        cursor.execute("""
            UPDATE users
            SET email=%s,
                account_type=%s,
                street_address=%s,
                city=%s,
                state=%s,
                zip_code=%s,
                phone=%s,
                latitude=%s,
                longitude=%s
            WHERE email=%s
        """, (
            new_email,
            request.form['account_type'],
            street,
            city,
            state,
            zip_code,
            phone,
            lat,
            lon,
            current_email
        ))

        # Save changes to database
        db.commit()
        # Update session email if it was changed
        session['user_email'] = new_email
        # Redirect to homepage after update
        return redirect("/homepage")

    # If GET request, fetch user data to display on profile page
    cursor.execute("""
        SELECT first_name, last_name, email, street_address, city, state, zip_code, phone, account_type
        FROM users WHERE email=%s
    """, (current_email,))
    user = cursor.fetchone()

    # Render profile page with user data
    return render_template("profile.html", user=user)

# ---------------- HOMEPAGE ----------------
# Route for the main dashboard after login
@app.route('/homepage')
def homepage():
    # Ensure user is logged in
    if 'user_email' not in session:
        return redirect("/login")

    # Get logged-in user's email
    user_email = session['user_email']

    # Count how many jobs are currently assigned to the user and in progress
    cursor.execute("""
        SELECT COUNT(*) FROM jobs 
        WHERE assigned_to=%s AND status='in_progress'
    """, (user_email,))
    job_count = cursor.fetchone()[0]

    # Render homepage and pass job count for display
    return render_template('homepage.html', job_count=job_count)


# ---------------- REQUEST SERVICES ----------------
# Route for users to create (request) a job
@app.route('/request_services', methods=['GET', 'POST'])
def request_services():
    # Ensure user is logged in
    if 'user_email' not in session:
        return redirect("/login")

    # Get logged-in user's email
    email = session['user_email']

    # Predefined list of job titles for users to select from
    job_titles = [
        "Lawn Mowing",
        "Snow Shoveling",
        "Leaf Raking",
        "Car Wash",
        "Mulching",
        "Junk Removal",
        "Pool Cleaning",
        "Fence Painting",
        "Weeding",
        "Dog Walking",
        "Window Cleaning",
        "Gutter Cleaning",
        "Moving Help",
        "Pressure Washing",
        "Hedge Trimming",
        "Trash Removal",
        "Furniture Assembly",
        "Light Cleaning",
        "Garage Cleaning",
        "Yard Cleanup",
        "Snow Removal",
        "Pet Sitting",
        "Tree Trimming",
        "Driveway Sealing",
        "Deck Cleaning",
        "Laundry Help",
        "Packing Help",
        "Basement Cleaning",
        "Garage Organization",
        "Fence Repair",
        "Light Yard Work",
        "Weed Removal",
        "Snow Shoveling",
        "Car Detailing",
        "Pool Skimming",
        "Roof Cleaning",
        "Sidewalk Cleaning",
        "Mailbox Repair",
        "Fence Cleaning",
        "Garden Setup",
        "Moving Boxes",
        "Trash Pickup",
        "Closet Organization",
        "Basement Sorting",
        "Driveway Cleaning",
        "Light Painting",
        "Furniture Moving",
        "Window Washing",
        "Yard Sweeping",
        "Leaf Blowing"
    ]

    # Fetch user profile info to auto-fill the form
    cursor.execute("""
        SELECT first_name, last_name, email, street_address, city, state, zip_code
        FROM users WHERE email=%s
    """, (email,))
    user = cursor.fetchone()

    # If form is submitted
    if request.method == 'POST':
        # Get job details from form
        title = request.form['title']
        description = request.form['description']
        price = request.form['price']
        street = request.form['street_address']
        city = request.form['city']
        state = request.form['state']
        zip_code = request.form['zip_code']

        # Convert address into coordinates using geocoding
        address = f"{street}, {city}, {state}, {zip_code}"
        location = do_geocode(address)
        if location:
            lat = location.latitude
            lon = location.longitude
        else:
            lat = lon = 0

        # Insert new job into database
        cursor.execute("""
            INSERT INTO jobs 
            (title, description, price, street_address, city, state, zip_code, requested_by, status, latitude, longitude, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'open',%s,%s,NOW())
        """, (title, description, price, street, city, state, zip_code, email, lat, lon))
        # Save changes
        db.commit()

        # Redirect to homepage after creating job
        return redirect("/homepage")
    
    # Render job request page with job titles and user info
    return render_template("request_services.html", job_titles=job_titles, user=user)

# ---------------- PROVIDE SERVICES ----------------
# Route for users to browse and apply for available jobs
@app.route('/provide_services')
def provide_services():
    # Ensure user is logged in
    if 'user_email' not in session:
        return redirect("/login")

    # Get filter/sort parameters from URL
    sort = request.args.get('sort')
    distance_filter = request.args.get('distance')
    titles_filter = request.args.get('titles')  # comma-separated titles

    # Get user's location for distance calculations
    cursor.execute("SELECT latitude, longitude, city, state FROM users WHERE email=%s", (session['user_email'],))
    user_loc = cursor.fetchone()

    if user_loc:
        user_lat, user_lon, user_city, user_state = user_loc
    else:
        user_lat = user_lon = 0
        user_city = user_state = ""

    # Retrieve all open jobs not created by the current user
    cursor.execute("""
        SELECT id, title, description, price, street_address, city, state, zip_code,
            requested_by, status, created_at, latitude, longitude
        FROM jobs
        WHERE status='open' AND requested_by != %s
    """, (session['user_email'],))
    jobs = cursor.fetchall()

    # Build a dictionary counting how many jobs exist per title
    job_titles = {}
    for job in jobs:
        title = job[1]
        if title in job_titles:
            job_titles[title] += 1
        else:
            job_titles[title] = 1

    # Filter jobs by selected titles if provided
    if titles_filter:
        selected_titles = titles_filter.split(',')
        jobs = [job for job in jobs if job[1] in selected_titles]

    # Calculate distance between user and each job
    jobs_with_distance = []

    for job in jobs:
        job_lat = job[11] if job[11] is not None else 0
        job_lon = job[12] if job[12] is not None else 0
        job_city = job[5]
        job_state = job[6]

        # If job is in the same city/state, treat distance as 0
        if job_city and job_state and user_city and user_state and \
           job_city.lower() == user_city.lower() and job_state.lower() == user_state.lower():
            distance = 0
            display_distance = "In your city"
        else:
            try:
                # Calculate geographic distance in miles
                distance = geodesic((user_lat, user_lon), (job_lat, job_lon)).miles
                distance = round(distance, 2)
                display_distance = f"{distance} miles"
            except:
                # Handle any calculation errors
                distance = None
                display_distance = "Unavailable"

        # Append distance info to job tuple
        jobs_with_distance.append(job + (distance, display_distance))

    # Filter jobs by maximum distance if provided
    if distance_filter:
        try:
            max_distance = float(distance_filter)
            jobs_with_distance = [
                job for job in jobs_with_distance
                if job[13] is not None and job[13] <= max_distance
            ]
        except:
            pass

    # Sort jobs based on selected option
    if sort == 'low':
        # Sort by price (low to high)
        jobs_with_distance.sort(key=lambda x: x[3])  
    elif sort == 'high':
        # Sort by price (high to low)
        jobs_with_distance.sort(key=lambda x: -x[3])  
    else:
        # Default sorting by distance (closest first)
        jobs_with_distance.sort(key=lambda x: x[13] if x[13] is not None else 9999)

    # Render page with jobs, title counts, and selected filters
    return render_template(
        "provide_services.html",
        jobs=jobs_with_distance,
        job_titles=job_titles,
        selected_titles=titles_filter
    )

# ---------------- APPLY FOR JOB ----------------
# Allows a user to apply for a specific job
@app.route('/apply_job', methods=['POST'])
def apply_job():
    # Ensure user is logged in
    if 'user_email' not in session:
        return redirect("/login")

    # Get current user and job ID from form
    user_email = session['user_email']
    job_id = request.form.get('job_id')

    # Check if the user has already applied to this job
    cursor.execute("""
        SELECT * FROM job_applications
        WHERE job_id=%s AND worker_email=%s
    """, (job_id, user_email))
    existing = cursor.fetchone()

    if not existing:
        # Insert a new application with timestamp and default status
        cursor.execute("""
            INSERT INTO job_applications (job_id, worker_email, applied_at, status)
            VALUES (%s, %s, NOW(), 'applied')
        """, (job_id, user_email))
        # Save changes
        db.commit()
        # Return response indicating successful application
        return "applied"
    else:
        # Prevent duplicate applications
        return "already_applied"
    
# ---------------- CHECK IF APPLIED ----------------
# Checks whether the current user has already applied to a job
@app.route('/check_applied/<int:job_id>')
def check_applied(job_id):
    # Ensure user is logged in
    if 'user_email' not in session:
        return "not_logged_in"

    user_email = session['user_email']

    # Query database for existing application
    cursor.execute("""
        SELECT * FROM job_applications
        WHERE job_id=%s AND worker_email=%s
    """, (job_id, user_email))
    existing = cursor.fetchone()

    # Return status for frontend logic (e.g., disable apply button)
    if existing:
        return "applied"
    else:
        return "not_applied"
    
# ---------------- ACCEPT WORKER ----------------
# Allows a job requester to accept one applicant and reject others
@app.route('/accept_worker', methods=['POST'])
def accept_worker():
    # Ensure user is logged in
    if 'user_email' not in session:
        return "not_logged_in"

    # Get form data
    job_id = request.form.get('job_id')
    worker_email = request.form.get('worker_email')
    requester_email = session['user_email']

    # Verify that the logged-in user is the owner of the job
    cursor.execute("SELECT requested_by FROM jobs WHERE id=%s", (job_id,))
    owner = cursor.fetchone()
    if not owner or owner[0] != requester_email:
        return "unauthorized"

    # Accept the selected worker
    cursor.execute("""
        UPDATE job_applications
        SET status='accepted', accepted=TRUE
        WHERE job_id=%s AND worker_email=%s
    """, (job_id, worker_email))

    # Reject all other applicants for this job
    cursor.execute("""
        UPDATE job_applications
        SET status='denied', accepted=FALSE
        WHERE job_id=%s AND worker_email != %s
    """, (job_id, worker_email))

    # Update job to assign the selected worker
    cursor.execute("""
        UPDATE jobs
        SET assigned_to=%s, status='assigned'
        WHERE id=%s
    """, (worker_email, job_id))

    # Save all changes
    db.commit()
    return redirect("/my_jobs")

# ---------------- MY JOBS ----------------
# Displays jobs the user has requested and jobs they have applied for
@app.route('/my_jobs')
def my_jobs():
    # Ensure user is logged in
    if 'user_email' not in session:
        return redirect("/login")

    user_email = session['user_email']

    # Get user's location for distance calculations
    cursor.execute(
        "SELECT latitude, longitude, city, state FROM users WHERE email=%s",
        (user_email,)
    )
    user_loc = cursor.fetchone()
    if user_loc:
        user_lat, user_lon, user_city, user_state = user_loc
    else:
        user_lat = user_lon = 0
        user_city = user_state = ""

    # ----------------- Jobs requested by this user -----------------
    cursor.execute("""
        SELECT j.id, j.title, j.price, j.city, j.state, j.latitude, j.longitude, j.assigned_to, j.status
        FROM jobs j
        WHERE j.requested_by=%s
    """, (user_email,))
    requested_jobs = cursor.fetchall()

    requested_with_distance = []
    for job in requested_jobs:
        job_lat = job[5] if job[5] else 0
        job_lon = job[6] if job[6] else 0

        try:
            distance = geodesic((user_lat, user_lon), (job_lat, job_lon)).miles
            distance = round(distance, 2)
        except:
            distance = None

        requested_with_distance.append(job)

    # ----------------- Jobs this user applied for -----------------
    cursor.execute("""
        SELECT j.id, j.title, j.price, j.city, j.state,
            j.latitude, j.longitude,
            j.status AS job_status,
            ja.status AS app_status,
            ja.accepted
        FROM jobs j
        JOIN job_applications ja ON j.id = ja.job_id
        WHERE ja.worker_email=%s
    """, (user_email,))
    applied_jobs = cursor.fetchall()

    # Extract status fields
    applied_with_distance_status = []
    for job in applied_jobs:
        job_lat = job[5] if job[5] else 0
        job_lon = job[6] if job[6] else 0
        app_status = job[8]     
        job_status = job[7]     
        accepted_flag = job[9]  

        # Calculate distance
        try:
            distance = geodesic((user_lat, user_lon), (job_lat, job_lon)).miles
            distance = round(distance, 2)
        except:
            distance = None

        # Determine display status for UI
        if accepted_flag:
            if job_status == 'assigned':
                status_display = "Assigned (Not Started)"
            elif job_status == 'in_progress':
                status_display = "In Progress"
            elif job_status == 'done':
                status_display = "Completed"
            else:
                status_display = "Assigned"
        elif app_status == 'denied':
            status_display = "Denied"
        else:
            status_display = "Applied"

        # Append job data with distance and display status
        applied_with_distance_status.append(job + (distance, status_display))

    # Render page with both requested and applied jobs
    return render_template(
        "my_jobs.html",
        requested_jobs=requested_with_distance,
        applied_jobs=applied_with_distance_status
    )

# ---------------- JOB DETAILS ----------------
# Displays detailed information about a specific job
@app.route('/job_details/<int:job_id>')
def job_details(job_id):
    # Ensure user is logged in
    if 'user_email' not in session:
        return redirect("/login")

    # Retrieve job information from database
    cursor.execute("""
        SELECT id, title, description, price, street_address, city, state, zip_code, assigned_to, requested_by, status
        FROM jobs WHERE id=%s
    """, (job_id,))
    job = cursor.fetchone()
    # If job does not exist, return error
    if not job:
        return "Job not found"

    # If job already has an assigned worker, redirect to my_jobs page
    if job[8] is not None:
        return redirect("/my_jobs")

    # Render job details page
    return render_template("job_details.html", job=job)


# ---------------- JOB APPLICATIONS ----------------
# Displays all applicants for a specific job
@app.route('/job_applications/<int:job_id>')
def job_applications(job_id):
    # Ensure user is logged in
    if 'user_email' not in session:
        return redirect("/login")

    # Retrieve job information
    cursor.execute("SELECT * FROM jobs WHERE id=%s", (job_id,))
    job = cursor.fetchone()
    if not job:
        return "Job not found"
    
    # Prevent viewing applicants if a worker has already been accepted
    cursor.execute("""
        SELECT COUNT(*) FROM job_applications
        WHERE job_id=%s AND accepted=TRUE
    """, (job_id,))
    accepted_count = cursor.fetchone()[0]

    if accepted_count > 0:
        return "You have already accepted a worker for this job."

    # Get current user's location for distance calculation
    cursor.execute("SELECT latitude, longitude, city, state FROM users WHERE email=%s", (session['user_email'],))
    user_loc = cursor.fetchone()
    if user_loc:
        user_lat, user_lon, user_city, user_state = user_loc
    else:
        user_lat = user_lon = 0
        user_city = user_state = ""

    # Retrieve all applicants for this job
    cursor.execute("""
        SELECT u.first_name, u.last_name, u.email, u.phone, u.latitude, u.longitude, u.city, u.state
        FROM job_applications ja
        JOIN users u ON ja.worker_email = u.email
        WHERE ja.job_id=%s
    """, (job_id,))
    applicants = cursor.fetchall()

    # Calculate distance between requester and each applicant
    applicants_with_distance = []

    for a in applicants:
        worker_first, worker_last, worker_email, worker_phone, worker_lat, worker_lon, worker_city, worker_state = a

        # Ensure coordinates are valid numbers
        try:
            worker_lat = float(worker_lat) if worker_lat else 0
            worker_lon = float(worker_lon) if worker_lon else 0
        except:
            worker_lat = worker_lon = 0

        # If in same city/state, set distance to 0
        if user_city and user_state and worker_city and worker_state and \
           user_city.lower() == worker_city.lower() and user_state.lower() == worker_state.lower():
            distance = 0
            display_distance = "In your city"
        else:
            try:
                distance = round(geodesic((user_lat, user_lon), (worker_lat, worker_lon)).miles, 2)
                display_distance = f"{distance} miles"
            except:
                distance = None
                display_distance = "Unavailable"

        # Store applicant info with distance
        applicants_with_distance.append((worker_first, worker_last, worker_email, worker_phone, distance, display_distance))

    # Render applicants page
    return render_template("job_applications.html", job=job, applicants=applicants_with_distance)


# ---------------- ACCEPT WORKER ----------------
# Accept a worker for a job (URL-based version)
@app.route('/accept_worker/<int:job_id>/<worker_email>')
def accept_worker_route(job_id, worker_email):
    # Ensure user is logged in
    if 'user_email' not in session:
        return redirect("/login")

    requester_email = session['user_email']

    # Verify current user owns the job
    cursor.execute("SELECT requested_by FROM jobs WHERE id=%s", (job_id,))
    job_owner = cursor.fetchone()
    if not job_owner or job_owner[0] != requester_email:
        return "Unauthorized"
    
    # Verify current user owns the job
    cursor.execute("SELECT assigned_to FROM jobs WHERE id=%s", (job_id,))
    existing = cursor.fetchone()

    if existing and existing[0] is not None:
        return redirect("/my_jobs")

    # Accept selected worker
    cursor.execute("""
        UPDATE job_applications
        SET status='accepted', accepted=TRUE
        WHERE job_id=%s AND worker_email=%s
    """, (job_id, worker_email))

    # Verify current user owns the job
    cursor.execute("""
        UPDATE job_applications
        SET status='denied', accepted=FALSE
        WHERE job_id=%s AND worker_email != %s
    """, (job_id, worker_email))

    # Verify current user owns the job
    cursor.execute("""
        UPDATE jobs
        SET assigned_to=%s, status='assigned'
        WHERE id=%s
    """, (worker_email, job_id))

    # Verify current user owns the job
    db.commit()
    return redirect("/my_jobs")

# ---------------- REJECT WORKER ----------------
# Reject a specific applicant
@app.route('/reject_worker/<int:job_id>/<worker_email>')
def reject_worker_route(job_id, worker_email):
    # Ensure user is logged in
    if 'user_email' not in session:
        return redirect("/login")

    requester_email = session['user_email']

    # Verify job ownership
    cursor.execute("SELECT requested_by FROM jobs WHERE id=%s", (job_id,))
    job_owner = cursor.fetchone()
    if not job_owner or job_owner[0] != requester_email:
        return "Unauthorized"

    # Update application status to denied
    cursor.execute("""
        UPDATE job_applications
        SET status='denied'
        WHERE job_id=%s AND worker_email=%s
    """, (job_id, worker_email))

    db.commit()
    return redirect(f"/job_applications/{job_id}")

# ---------------- UPDATE JOB STATUS ----------------
# Allows assigned worker to update job progress status
@app.route('/update_job_status/<int:job_id>', methods=['POST'])
def update_job_status(job_id):
    # Ensure user is logged in
    if 'user_email' not in session:
        return redirect("/login")

    user_email = session['user_email']
    new_status = request.form.get('status')

    # Get current job assignment and status
    cursor.execute("SELECT assigned_to, status FROM jobs WHERE id=%s", (job_id,))
    job = cursor.fetchone()

    if not job:
        return "Job not found"

    assigned_to, current_status = job

    # Ensure only the assigned worker can update status
    if assigned_to != user_email:
        return "Unauthorized"

    # Define valid status transitions
    valid_transitions = {
        "assigned": ["in_progress"],
        "in_progress": ["done"],
        "done": []
    }

    # Validate current status
    if current_status not in valid_transitions:
        return "Invalid current status"

    # Validate requested transition
    if new_status not in valid_transitions[current_status]:
        return "Invalid status transition"

    # Update job status
    cursor.execute(
        "UPDATE jobs SET status=%s WHERE id=%s",
        (new_status, job_id)
    )
    db.commit()

    return redirect("/my_jobs")

# ---------------- LOGOUT ----------------
# Clears session and logs user out
@app.route('/logout')
def logout():
    session.clear()
    return redirect("/login")

# ---------------- APP ENTRY POINT ----------------
# Runs the Flask application in debug mode
if __name__ == '__main__':
    app.run(debug=True)