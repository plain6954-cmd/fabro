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

## Supabase complaint media

Production complaint attachments use direct browser-to-Supabase uploads. Django
creates a server-controlled path and a two-hour Supabase signed-upload URL. The
browser uploads the file directly, then submits only the opaque upload ID to
Django. Django verifies ownership, path, object metadata, size, MIME type and the
10-file limit before creating `ComplaintMedia`. Download links are also signed by
an authenticated Django endpoint, so the bucket can remain private.

Required production variables:

```text
USE_SUPABASE_STORAGE=True
SUPABASE_URL=https://PROJECT_REF.supabase.co
SUPABASE_SERVICE_ROLE_KEY=server-only-service-role-key
SUPABASE_STORAGE_BUCKET=fabro-leather-media
```

Optional variables are `SUPABASE_SIGNED_DOWNLOAD_TTL_SECONDS` (default `300`)
and `SUPABASE_STORAGE_HTTP_TIMEOUT_SECONDS` (default `15`). Never expose the
service-role key in HTML, JavaScript, Flutter, or a public environment variable.

Create a **private** standard Storage bucket whose ID exactly matches
`SUPABASE_STORAGE_BUCKET`. Configure its maximum file size as 100 MB and allow
only these MIME types: `image/jpeg`, `image/png`, `image/webp`, `image/gif`,
`video/mp4`, `video/quicktime`, `video/webm`, `video/x-msvideo`, `video/avi`, and
`video/x-matroska`. Browser uploads use signed tokens created by the server-side
service role, so no public or anonymous INSERT policy is required. Do not add a
policy that lets clients choose arbitrary object paths.

Incomplete uploads expire after two hours. Schedule the following command at
least hourly in the production scheduler to remove abandoned objects:

```bash
python manage.py cleanup_abandoned_media_uploads
```

Local development and automated tests retain the existing multipart upload to
`MEDIA_ROOT` by leaving `USE_SUPABASE_STORAGE=False`.

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
