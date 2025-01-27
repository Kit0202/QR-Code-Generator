from flask import Flask, render_template, Blueprint, redirect, url_for, request, flash, send_file, send_from_directory, make_response, current_app, session
from jinja2 import ChoiceLoader, FileSystemLoader
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_migrate import Migrate
from io import BytesIO
import qrcode
import base64
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename
import os
import io
from PIL import Image, ImageDraw, ImageFont, ImageColor
import re
from datetime import datetime, timezone
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import SquareModuleDrawer, CircleModuleDrawer, RoundedModuleDrawer, VerticalBarsDrawer, HorizontalBarsDrawer, GappedSquareModuleDrawer
from qrcode.image.styles.colormasks import SolidFillColorMask


app = Flask(__name__)
app.secret_key = 'your_secret_key'

app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:0202@localhost:5432/qr_code_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 *1024 # Maximum file size: 16 MB
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'png', 'jpg', 'jpeg', 'gif'}
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB limit
app.config['UPLOAD_FOLDER'] = os.path.join(app.instance_path, 'uploads')


ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_image_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'main.login'

main = Blueprint('main', __name__)

# User model
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), nullable=False, unique=True)
    email = db.Column(db.String(150), nullable=False, unique=True)
    password = db.Column(db.String(150), nullable=False)
    
class QRCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    data = db.Column(db.Text, nullable=False)  # Store the QR code image as base64
    redirect_url = db.Column(db.Text, nullable=True)  # Store the URL to redirect to
    vcard_data = db.Column(db.Text, nullable=True)  # Store vCard data
    type = db.Column(db.String(50), nullable=False)  # New field to indicate the type of QR code (e.g., 'url', 'image')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref=db.backref('qrcodes', lazy=True))
    scan_count = db.Column(db.Integer, default=0)
    
    def __repr__(self):
        return f'<QRCode {self.name}>'
    
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Registration Form
class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register')

    def __repr__(self):
        return f'<QRScan {self.qr_id} at {self.timestamp}>'
    
    
class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Optional foreign key
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    submitted_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref='contacts', lazy=True)  # Optional relationship to User

    def __repr__(self):
        return f"Contact('{self.name}', '{self.email}', '{self.subject}')"
    
@main.errorhandler(413)
def request_entity_too_large(error):
    flash('File is too large. Please upload a smaller file.', 'danger')
    return redirect(request.url)

@main.route('/')
def home():
    return render_template('home.html')

@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        if email and password:
            user = User.query.filter_by(email=email).first()
            if user and bcrypt.check_password_hash(user.password, password):
                login_user(user)
                flash('Login successful!', 'success')
                return redirect(url_for('main.dashboard'))
            else:
                flash('Invalid credentials', 'danger')
        else:
            flash('Email and password are required', 'danger')
    return render_template('login.html')

@main.route('/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data, password=bcrypt.generate_password_hash(form.password.data).decode('utf-8'))
        try:
            db.session.add(user)
            db.session.commit()
            flash('Registration successful!', 'success')
            return redirect(url_for('login'))
        except IntegrityError:
            db.session.rollback()
            form.email.errors.append('This email is already registered. Please use a different email.')
    return render_template('register.html', form=form)

@main.route('/dashboard')
@login_required
def dashboard():
    page = request.args.get('page', 1, type=int)
    per_page = 15  # Number of items per page
    qr_codes_pagination = QRCode.query.filter_by(user_id=current_user.id).paginate(page=page, per_page=per_page)
    return render_template('dashboard.html', qr_codes_pagination=qr_codes_pagination)

@main.route('/delete_qr/<int:qr_id>', methods=['POST'])
@login_required
def delete_qr(qr_id):
    qr = QRCode.query.get_or_404(qr_id)
    
    # Ensure the user is authorized to delete this QR code
    if qr.user_id != current_user.id:
        flash('You do not have permission to delete this QR code', 'danger')
        return redirect(url_for('main.dashboard'))
    
    # Delete the QR code from the database
    db.session.delete(qr)
    db.session.commit()
    
    flash('QR Code deleted successfully!', 'success')
    return redirect(url_for('main.dashboard'))

@main.route('/download_qr/<int:qr_id>', methods=['GET'])
@login_required
def download_qr(qr_id):
    qr = QRCode.query.get_or_404(qr_id)
    
    # Ensure the user is authorized to download this QR code
    if qr.user_id != current_user.id:
        flash('You do not have permission to download this QR code', 'danger')
        return redirect(url_for('main.dashboard'))
    
    # Generate QR code image from base64 data
    img_data = base64.b64decode(qr.data)
    
    # Create an in-memory file object
    img_io = io.BytesIO(img_data)
    
    # Return the image file as a download
    return send_file(img_io, mimetype='image/png', as_attachment=True, download_name=f"{qr.name}.png")

@main.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.login'))

@main.route('/why_us')
def why_us():
    return render_template('why_us.html',
                           page_name='why_us',
                           banner_title='Why Us',
                           banner_text='Discover the power of seamless and efficient QR code generation with our innovative platform. Whether you are a business or an individual, our customizable, dynamic QR codes offer unparalleled convenience and versatility. Join us and unlock new possibilities.')

@main.route('/faq')
def faqs():
    accordion_items = [
        {"title": "What are the benefits of using an account?", "content": "By creating an account you can store all your created QR codes in one place; see the statistics on each code’s scan; delete QR codes; change the content of QR codes without changing the appearance; change the QR code type; use ALL QR codes without advertising, in case of buying a subscription."},
        {"title": "After subscribing to the Premium version, will the ads be removed for free QR?", "content": "Yes, ads will be removed, but codes should be in the account."},
        {"title": "Will I lose all the QR after my subscription ended?", "content": "No, all your codes will work, just ads will be shown again."},
        {"title": "What are my payment options?", "content": "You can either pay with credit card or any debit card you want! All our payments are secured"}
    ]
    return render_template('faq.html', 
                           page_name='faq',
                           banner_title='Frequently Asked Question',
                           banner_text='Below we have collected answers to the most common questions you may have. Our goal is to provide clear and helpful information to address any concerns or queries you might encounter while using our services.',
                           get_in_touch_text='If you have more question, feel free to contact us.',
                           accordion_items=accordion_items)
    
@main.route('/pricing')
def pricing():
    return render_template('pricing.html',
                           page_name='pricing',
                           banner_title='Plans & Pricing',
                           banner_text='Explore our range of plans to find the perfect fit for your needs. Whether you are an individual, a small business , or a large enterprise. Compare the features and benefits of each plan to determine the best value for your requirements. Choose a plan that aligns with your goals and budget, and get started today!')
    
@main.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        subject = request.form.get('subject')
        message = request.form.get('message')
        
        if not (name and email and subject and message):
            flash('All fields are required.', 'danger')
            return redirect(url_for('main.contact'))
        
        #Create a new Contact object
        new_contact = Contact(
            name=name,
            email=email,
            subject=subject,
            message=message,
            submitted_at=datetime.now(timezone.utc)
        )
        
        try:
            db.session.add(new_contact)
            db.session.commit()
            flash('Your message has been submitted successfully.', 'success')
            return redirect(url_for('main.contact'))
        except Exception as e:
            db.session.rollback()
            flash(f'An error occurred while submitting your message. Please try again', 'danger')
    
    return render_template('contact.html',
                           page_name='contact',
                           banner_title='Contact Us',
                           banner_text='Whether you have a question, need support, or want to provide feedback, our team is ready to assist you. Feel free to reach out to us through the form below, and we will get back to you as soon as possible. Your satisfaction is our priority, and we look forward to hearing from you.')
    
@main.route('/about_us')
def about_us():
    return render_template('about_us.html',
                           page_name='about_us',
                           banner_title='About Us',
                           banner_text='Learn more about our mission, vision, and the dedicated team behind our innovative solutions. Discover how we are committed to providing exceptional services and driving success for our clients. Our journey is defined by a passion for excellence and a commitment to continuous improvement.')

@main.route('/url_qr', methods=['GET', 'POST'])
@login_required
def url_qr():
    if request.method == 'POST':
        url = request.form['url']
        name = request.form['name']
        
        # Create a QRCode entry in the database
        qr_entry = QRCode(name=name, data='', redirect_url=url, vcard_data=None, type='url', user_id=current_user.id)
        db.session.add(qr_entry)
        db.session.commit()  # Save to generate an ID
        
        # Store data in session
        session['qr_data'] = url
        session['name'] = name
        session['qr_type'] = 'url'
        session['qr_id'] = qr_entry.id
        
        # Redirect to the customization page with QR data
        return redirect(url_for('main.customize_qr'))
        
    return render_template('url_qr.html')


# Consolidated allowed_file function
def allowed_file(filename, filetype):
    allowed_extensions = {
        'image': {'png', 'jpg', 'jpeg', 'gif'},
        'pdf': {'pdf'}
    }
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions[filetype]


@main.route('/image_qr', methods=['GET', 'POST'])
@login_required
def image_qr():
    if request.method == 'POST':
        if 'image' not in request.files:
            flash('No image file part', 'danger')
            return redirect(request.url)
        file = request.files['image']
        name = request.form['name']
        
        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(request.url)
        
        if file and allowed_file(file.filename, 'image'):
            # Convert image to base64
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.root_path, 'static/uploads', filename)
            file.save(file_path)
            
            # Create a URL to access the image
            image_url = url_for('static', filename='uploads/' + filename, _external=True)
            
            # Create a QRCode entry in the database
            qr_entry = QRCode(name=name, data='', redirect_url=image_url, vcard_data=None, type='image', user_id=current_user.id)
            db.session.add(qr_entry)
            db.session.commit()  # Save to generate an ID
            
            # Save the image URL and filename in the session
            session['qr_data'] = image_url
            session['name'] = name
            session['qr_type'] = 'image'
            session['qr_id'] = qr_entry.id
            
            # Redirect to the customization page with image URL
            return redirect(url_for('main.customize_qr'))

    return render_template('image_qr.html')

@main.route('/display_file/<filename>')
def display_file(filename):
    try:
        # Ensure the file exists before serving it
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(file_path):
            return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
        else:
            flash('File not found.', 'danger')
            return redirect(url_for('main.dashboard'))
    except Exception as e:
        flash(f"Error: {str(e)}", 'danger')
        return redirect(url_for('main.dashboard'))


@main.route('/pdf_qr', methods=['GET', 'POST'])
@login_required
def pdf_qr():
    if request.method == 'POST':
        if 'pdf' not in request.files:
            flash('No file part', 'danger')
            return redirect(request.url)
        file = request.files['pdf']
        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(request.url)
        if file and allowed_file(file.filename, 'pdf'):
            name = request.form['name']
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            file_url = url_for('main.display_pdf', filename=filename, _external=True)
            
            # Create a QRCode entry in the database
            qr_entry = QRCode(name=name, data='', redirect_url=file_url, vcard_data=None, type='pdf', user_id=current_user.id)
            db.session.add(qr_entry)
            db.session.commit()  # Save to generate an ID
            
            session['qr_data'] = file_url
            session['name'] = name
            session['qr_type'] = 'pdf'
            session['qr_id'] = qr_entry.id

            return redirect(url_for('main.customize_qr'))
        else:
            flash('Allowed file type is pdf', 'danger')

    return render_template('pdf_qr.html')

@main.route('/display_pdf/<filename>')
def display_pdf(filename):
    try:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True)
        else:
            flash('File not found.', 'danger')
            return redirect(url_for('main.dashboard'))
    except Exception as e:
        flash(f"Error: {str(e)}", 'danger')
        return redirect(url_for('main.dashboard'))
    
@main.route('/whatsapp_qr', methods=['GET', 'POST'])
@login_required
def whatsapp_qr():
    if request.method == 'POST':
        country_code = request.form['country_code']
        phone_number = request.form['phone_number']
        message = request.form['message']
        name = request.form['name']
        
        if not phone_number:
            flash('Phone number is required', 'danger')
            return redirect(request.url)
        
        # Create WhatsApp link
        whatsapp_url = f"https://wa.me/{country_code}{phone_number}?text={message}"
        
        # Create a QRCode entry in the database
        qr_entry = QRCode(name=name, data='', redirect_url=whatsapp_url, vcard_data=None, type='whatsapp', user_id=current_user.id)
        db.session.add(qr_entry)
        db.session.commit()  # Save to generate an ID
        
        # Save data in the session
        session['qr_data'] = whatsapp_url
        session['name'] = name
        session['qr_type'] = 'whatsapp'
        session['qr_id'] = qr_entry.id

        return redirect(url_for('main.customize_qr'))

    return render_template('whatsapp_qr.html')


@main.route('/vcard_qr', methods=['GET', 'POST'])
@login_required
def vcard_qr():
    qr_code = None
    image_url = None
    if request.method == 'POST':
        name = request.form['name']
        dob = request.form['dob']
        phone_number = request.form['phone_number']
        email = request.form['email']
        company = request.form['company']
        job_title = request.form['job_title']
        website = request.form['website']
        address = request.form['address']
        image = request.files.get('image')
        
        # Validate name (only alphabets and spaces)
        if not all(c.isalpha() or c.isspace() for c in name):
            flash('Name should contain only alphabets and spaces.', 'danger')
            return redirect(request.url)
        
        # Validate phone number (only numbers)
        if not phone_number.isdigit():
            flash('Phone number should contain only digits.', 'danger')
            return redirect(request.url)
        
        # Validate email format using regular expression
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_regex, email):
            flash('Invalid email address.', 'danger')
            return redirect(request.url)
        
        try:
            dob = request.form['dob']
            # Attempt to parse the date using multiple formats
            try:
                # Browser default format for <input type="date">
                parsed_dob = datetime.strptime(dob, '%Y-%m-%d')
            except ValueError:
                # Allow manual input in DD-MM-YYYY format
                parsed_dob = datetime.strptime(dob, '%d-%m-%Y')
            # Additional validation to ensure the date is realistic
            if parsed_dob.year < 1900 or parsed_dob.year > datetime.now().year:
                raise ValueError("Year out of valid range.")
        except ValueError:
            flash('Invalid date format or unrealistic date. Please use YYYY-MM-DD or DD-MM-YYYY.', 'danger')
            return redirect(request.url)
        
        # Save the image if valid
        if image and allowed_image_file(image.filename):
            filename = secure_filename(image.filename)
            image_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            image.save(image_path)
            image_url = url_for('main.display_file', filename=filename, _external=True)
        elif image:
            flash('Invalid image format. Allowed formats are JPG, JPEG, PNG, and GIF.', 'danger')
            return redirect(request.url)
        
        # Create vCard data
        vcard = f"""
        BEGIN:VCARD
        VERSION:3.0
        FN:{name}
        BDAY:{dob}
        TEL:{phone_number}
        EMAIL:{email}
        ORG:{company}
        TITLE:{job_title}
        URL:{website}
        ADR:{address}
        """
        if image_url:
            vcard += f"PHOTO;VALUE=URL:{url_for('main.serve_uploaded_image', filename=filename, _external=True)}\n"  # Include the image URL in the vCard
            
        vcard += "END:VCARD"
        
        # Create a QRCode entry in the database
        qr_entry = QRCode(name=name, data='',redirect_url=vcard, vcard_data=vcard, type='vcard', user_id=current_user.id)
        db.session.add(qr_entry)
        db.session.commit()  # Save to generate an ID
        
        # Store vCard data in session
        session['qr_data'] = vcard
        session['name'] = name
        session['qr_type'] = 'vcard'
        session['qr_id'] = qr_entry.id
        
        return redirect(url_for('main.customize_qr'))

    return render_template('vcard_qr.html', qr_code=qr_code, image_url=image_url)

@main.route('/uploads/<filename>')
def serve_uploaded_image(filename):
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)


@main.route('/view_vcard/<int:qr_id>', methods=['GET'])
def view_vcard(qr_id):
    qr_entry = QRCode.query.get_or_404(qr_id)
    # Parse the vCard data into individual fields
    vcard_data = qr_entry.vcard_data
    vcard_fields = parse_vcard(vcard_data)
    
    return render_template('view_vcard.html', vcard_fields=vcard_fields, qr_id=qr_id)

def parse_vcard(vcard_str):
    if not vcard_str:
        return {}

    vcard_info = {}
    lines = [line.strip() for line in vcard_str.strip().split('\n') if line.strip()]  # Remove empty and whitespace-only lines
    for line in lines:
        if line.startswith('FN:'):
            vcard_info['name'] = line[3:].strip()
        elif line.startswith('TEL:'):
            vcard_info['phone_number'] = line[4:].strip()
        elif line.startswith('EMAIL:'):
            vcard_info['email'] = line[6:].strip()
        elif line.startswith('ADR:'):
            vcard_info['address'] = line[4:].strip()
        elif line.startswith('ORG:'):
            vcard_info['company'] = line[4:].strip()
        elif line.startswith('TITLE:'):
            vcard_info['job_title'] = line[6:].strip()
        elif line.startswith('URL:'):
            vcard_info['website'] = line[4:].strip()
        elif line.startswith('BDAY:'):
            vcard_info['birthday'] = line[5:].strip()
        elif line.startswith('PHOTO;VALUE=URL:'):
            vcard_info['image_url'] = line[16:].strip()  # Extract image URL from vCard
    return vcard_info

@main.route('/download_vcard/<int:qr_id>')
def download_vcard(qr_id):
    qr_entry = QRCode.query.get_or_404(qr_id)
    vcard_data = qr_entry.vcard_data
    
    # Create a temporary file for the vCard
    temp_file = BytesIO()
    temp_file.write(vcard_data.encode('utf-8'))
    temp_file.seek(0)
    
    # Return the vCard as a downloadable file
    return send_file(
        temp_file,
        as_attachment=True,
        download_name=f'{qr_entry.name}_vcard.vcf',
        mimetype='text/vcard'
    )

@main.route('/customize_qr', methods=['GET', 'POST'])
@login_required
def customize_qr():
    qr_data = session.get('qr_data')
    name = session.get('name')
    qr_type = session.get('qr_type')
    qr_id = session.get('qr_id')

    return render_template('customize.html', qr_data=qr_data, name=name, qr_type=qr_type)


@main.route('/finalize_qr', methods=['POST'])
@login_required
def finalize_qr():
    qr_data = session.get('qr_data')
    name = session.get('name')
    qr_type = session.get('qr_type')
    qr_id = session.get('qr_id')
    
    fill_color = ImageColor.getrgb(request.form.get('fill_color', '#000000'))
    back_color = ImageColor.getrgb(request.form.get('back_color', '#ffffff'))
    error_correction = request.form.get('error_correction', 'L')
    box_size = int(request.form.get('box_size', 10))
    border = int(request.form.get('border', 4))
    dot_shape = request.form.get('dot_shape', 'square')
    marker_border_shape = request.form.get('marker_border_shape', 'square')
    marker_center_shape = request.form.get('marker_center_shape', 'square')
    qr_text = request.form.get('qr_text', '').strip()
    text_position = request.form.get('text_position', 'below')
    text_font_size = int(request.form.get('text_font_size', 40))
    text_font_style = request.form.get('text_font_style', 'arial')
    text_color = ImageColor.getrgb(request.form.get('text_color', '#000000'))
    
    
    # Avoid pure black background with black dots
    if back_color == (0, 0, 0):
        back_color = (1, 1, 1)  # Adjust slightly to ensure visibility
    
    # Map the shape options to qrcode-artistic styles
    dot_shapes = {
        "square": SquareModuleDrawer(),
        "circle": CircleModuleDrawer(),
        "rounded": RoundedModuleDrawer(),
        "vertical_bars": VerticalBarsDrawer(),
        "horizontal_bars": HorizontalBarsDrawer(),
        "gapped_square": GappedSquareModuleDrawer(),
    }
    marker_border_shapes = {
        "square": SquareModuleDrawer(),
        "circle": CircleModuleDrawer(),
        "rounded": RoundedModuleDrawer(),
        "vertical_bars": VerticalBarsDrawer(),
        "horizontal_bars": HorizontalBarsDrawer(),
        "gapped_square": GappedSquareModuleDrawer(),
    }
    marker_center_shapes = {
        "square": SquareModuleDrawer(),
        "circle": CircleModuleDrawer(),
        "rounded": RoundedModuleDrawer(),
        "gapped_square": GappedSquareModuleDrawer(), 
    }
    
    FONT_MAP = {
        'arial': 'arial.ttf',
        'times': 'view/app/fonts/times.ttf',
        'courier': 'view/app/fonts/courier.ttf',
        'calibri': 'view/app/fonts/calibri.ttf',
        'italic': 'view/app/fonts/italic.ttf',
        'bold': 'view/app/fonts/bold.ttf',
    }

    # Recreate QR code with updated settings
    qr = qrcode.QRCode(
        version=None,
        error_correction={
            'L': qrcode.constants.ERROR_CORRECT_L,
            'M': qrcode.constants.ERROR_CORRECT_M,
            'Q': qrcode.constants.ERROR_CORRECT_Q,
            'H': qrcode.constants.ERROR_CORRECT_H,
        }[error_correction],
        box_size=box_size,
        border=border,
    )
    # Generate the QR code with the URL pointing to the scan_qr route
    if qr_type == 'vcard':
        qr.add_data(url_for('main.scan_qr', qr_id=qr_id, _external=True))
    else:
        qr.add_data(url_for('main.scan_qr', qr_id=qr_id, _external=True))
    
    qr.make(fit=True)

    # Generate the image with custom colors
    img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=dot_shapes.get(dot_shape, SquareModuleDrawer()),
        eye_drawer=marker_border_shapes.get(marker_border_shape, SquareModuleDrawer()),
        eye_inner_drawer=marker_center_shapes.get(marker_center_shape, SquareModuleDrawer()),
        color_mask=SolidFillColorMask(
            front_color=fill_color,
            back_color=back_color
        ),
    )
    
    # Handle logo overlay
    logo = request.files.get('logo')
    predefined_logo = request.form.get('predefined_logo')
    logo_img = None

    if logo:
        logo_img = Image.open(io.BytesIO(logo.read())).convert("RGBA")
    elif predefined_logo and predefined_logo != 'custom':
        # Construct the absolute path for the predefined logo
        logo_path = os.path.join(os.getcwd(),'view', 'app', 'static', 'img', 'logos', f'{predefined_logo}.png')
        logo_path = logo_path.replace(os.sep, '/')  # Ensure compatibility with forward slashes

        # Check if the file exists and load it
        if os.path.exists(logo_path):
            try:
                logo_img = Image.open(logo_path).convert("RGBA")
            except Exception as e:
                return redirect(url_for('main.customize_qr'))
        else:
            flash(f'Selected predefined logo "{predefined_logo}" not found at {logo_path}.', 'error')
    else:
        logo_img = None

    if logo_img:
        # Calculate logo size and position
        img_w, img_h = img.size
        logo_size = min(img_w, img_h) // 6  # Logo size is 1/6th of the QR code size
        logo_img = logo_img.resize((logo_size, logo_size), Image.LANCZOS)
        
        pos = ((img_w - logo_size) // 2, (img_h - logo_size) // 2)
        img.paste(logo_img, pos, mask=logo_img.split()[3])
    else:
        flash('Logo not found. Please select a valid predefined logo or upload a custom logo.', 'error')
        
        
    # Add text if provided
    if qr_text:
        draw = ImageDraw.Draw(img)
        font_path = FONT_MAP.get(text_font_style, 'view/app/fonts/arial.ttf')  # Default to Arial if not found
        try:
            font = ImageFont.truetype(font_path, text_font_size)
        except IOError:
            font = ImageFont.load_default()

        text_width, text_height = draw.textbbox((0, 0), qr_text, font=font)[2:]
        
        # Resize the canvas to include space for the text
        if img.mode != 'RGBA':
            img = img.convert('RGBA')

        img_width, img_height = img.size
        if text_position == 'above':
            new_img = Image.new('RGBA', (img_width, img_height + text_height + 10), back_color)
            new_img.paste(img, (0, text_height + 1))
            text_position = (img_width // 2 - text_width // 2, 0)
        else:  # Below
            new_img = Image.new('RGBA', (img_width, img_height + text_height + 10), back_color)
            new_img.paste(img, (0, 0))
            text_position = (img_width // 2 - text_width // 2, img_height + 1)

        draw = ImageDraw.Draw(new_img)
        draw.text(text_position, qr_text, fill=text_color, font=font)
        img = new_img

    # Convert to base64 for rendering
    img_io = BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)
    qr_base64 = base64.b64encode(img_io.getvalue()).decode('utf-8')

    # Fetch the existing QR code entry and update it
    qr_entry = QRCode.query.get_or_404(qr_id)
    qr_entry.name = name
    qr_entry.data = qr_base64
    qr_entry.vcard_data = qr_data if qr_type == 'vcard' else None
    qr_entry.type = qr_type
    db.session.commit()
    
    session.pop('qr_data', None)
    session.pop('name', None)
    session.pop('qr_type', None)
    session.pop('qr_id', None)

    # Pass the QR code back to the template for display
    qr_code = f"data:image/png;base64,{qr_base64}"
    
    return render_template(
        'customize.html',
        qr_code=qr_code,
        qr_data=qr_data,
        name=name,
        qr_type=qr_type,  # Pass qr_type to the template as well
    )
    
@main.route('/scan_qr/<int:qr_id>', methods=['GET'])
def scan_qr(qr_id):
    qr_entry = QRCode.query.get_or_404(qr_id)
    
    # Increment the scan count
    qr_entry.scan_count += 1
    db.session.commit()
    
    # Redirect to the appropriate content based on the QR type
    if qr_entry.type == 'url':
        return redirect(qr_entry.redirect_url)
    elif qr_entry.type == 'image':
        return redirect(qr_entry.redirect_url)
    elif qr_entry.type == 'pdf':
        return redirect(qr_entry.redirect_url)
    elif qr_entry.type == 'whatsapp':
        return redirect(qr_entry.redirect_url)
    elif qr_entry.type == 'vcard':
        return redirect(url_for('main.view_vcard', qr_id=qr_id))
    else:
        flash('Invalid QR code type', 'danger')
        return redirect(url_for('main.index'))

@main.route('/analytics', methods=['GET'])
@login_required
def analytics():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    qr_codes_pagination = QRCode.query.filter_by(user_id=current_user.id).paginate(page=page, per_page=per_page)
    
    return render_template('analytics.html', qr_codes_pagination=qr_codes_pagination)


# New page route with dynamic variables
@main.route('/page')
def page():
    page_name = 'example'  # This can be dynamic
    banner_title = "Welcome to Our Page"
    banner_text = "Discover our services and book a consultation today."
    return render_template('your_template.html', 
                           page_name=page_name,
                           banner_title=banner_title, 
                           banner_text=banner_text)

# Register the blueprint with the app
app.register_blueprint(main)


app.jinja_loader = ChoiceLoader([
    app.jinja_loader,
    FileSystemLoader('C:/Users/YCK7T/Documents/qr-code-generator/view/app/partials')
])

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
    # host='0.0.0.0', port=5000,