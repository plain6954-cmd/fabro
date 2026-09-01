# Fabro Leather - Car Seat Management System

A full-featured Django-based management system built for Fabro Leather to streamline car seat complaint tracking, vehicle configurations, SKU inventory, and user access control — with a sleek dark-themed interface.

## 🚀 Features

- **🔧 Car Detail Management**  
  Add and manage car Brands, Models, Sub-Models, and Year Ranges with support for number of seats, doors, and layout code validation.

- **📋 Complaint Management**  
  Add complaints with media (images/videos), vehicle info, and master data like country, channel, case type, etc.

- **🧩 SKU Management**  
  Add and manage SKUs with descriptions. Includes CSV bulk upload support.

- **📂 Media Uploads**  
  Upload multiple images and videos per complaint. Files stored per complaint in organized folders.

- **🔐 User Access Control**  
  Role-based permissions, secure login/logout, and session handling.

- **💡 Light/Dark Mode Toggle**  
  Fully responsive modern UI with a light/dark theme switcher.

- **📊 Dashboard Tiles**  
  Interactive homepage with clickable tiles for quick access.

- **💬 Direct User-to-User Chat System (`CHAT` Window)**  
  Dedicated **CHAT** link on the top navigation bar accessible for every user. Features a clean 2-pane layout with a user directory list on the left and active message thread view on the right.

- **📌 Complaint-Linked Direct Messaging**  
  Initiate a direct text chat about any specific complaint (`PAT-XXXX`, `PRO-XXXX`, `LIN-XXXX`) directly from the **All Complaints** window.

---

## 📂 Project Structure

```bash
fabro_leather/
├── management/
│   ├── models.py
│   ├── views.py
│   ├── forms.py
│   ├── templates/
│   │   └── management/
│   │       ├── add_car_details.html
│   │       ├── add_complaint.html
│   │       ├── chat.html
│   │       ├── complaint_list.html
│   │       ├── add_sku.html
│   │       └── ...
├── static/
│   ├── css/
│   └── js/
├── media/
│   └── complaint_media/
├── fabro_leather/
│   ├── settings.py
│   ├── urls.py
├── templates/
│   └── registration/
│       ├── login.html
│       └── logout.html
├── requirements.txt
└── README.md
````

---

## 🛠️ Tech Stack

* **Backend**: Django (Python), PostgreSQL (via Supabase)
* **Frontend**: HTML, CSS (Dark Theme), JavaScript
* **Storage**: Supabase PostgreSQL (with media stored on disk or S3 alternative)
* **Auth**: Django Auth with custom templates
* **Deployment**: Docker, Terraform, Ansible (planned for AWS EC2)

---

## 📦 Installation

1. **Clone the repository**

```bash
git clone https://github.com/yourusername/fabro-leather.git
cd fabro-leather
```

2. **Create and activate virtual environment**

```bash
python -m venv env
source env/bin/activate  # Windows: env\Scripts\activate
```

3. **Install dependencies**

```bash
pip install -r requirements.txt
```

4. **Configure database in `settings.py`**
   (Using Supabase PostgreSQL credentials)

5. **Apply migrations and run server**

```bash
python manage.py migrate
python manage.py runserver
```

---

## 📁 CSV Bulk Uploads

* **SKU Upload**: Navigate to `/add_sku/` → Upload a `.csv` with `sku,description` columns.
* **Complaints**: Future support for complaint bulk upload planned.

---

## 📸 Screenshots

> *Add screenshots here for dashboard, complaint form, car detail form, etc.*

---

## 🧠 Future Enhancements

* WebSockets for real-time instant chat delivery
* Media annotation
* Audit logging and comment threads
* Notification system (email/SMS)
* Advanced analytics and reporting
* 2FA and session timeout control
* Mobile responsive views

---

## 🤝 Contributing

Pull requests are welcome! For major changes, please open an issue first.

---

## 📄 License

This project is proprietary and maintained by **Fabro Leather**. For internal use only.

---

```

Let me know if you want me to include badges (e.g. build status, license), or if you're planning to make this public and want an open-source license added.
```
"# fabro123" 
