(function () {
    'use strict';

    const language = ['en', 'ar', 'hi'].includes(window.FABRO_LANGUAGE)
        ? window.FABRO_LANGUAGE
        : 'en';
    const root = document.documentElement;
    root.lang = language;
    // Translations change the copy only; the portal shell keeps its established LTR layout.
    root.dir = 'ltr';

    if (language === 'en') return;

    const translations = {
        'Dashboard': ['لوحة التحكم', 'डैशबोर्ड'], 'Add Complaint': ['إضافة شكوى', 'शिकायत जोड़ें'],
        'Complaints': ['الشكاوى', 'शिकायतें'], 'Vehicles': ['المركبات', 'वाहन'], 'Vehicle': ['المركبة', 'वाहन'],
        'SKU': ['رمز المنتج', 'एसकेयू'], 'Master': ['الإعدادات الرئيسية', 'मास्टर'], 'Approvals': ['الموافقات', 'अनुमोदन'],
        'Approvals Workspace': ['مساحة عمل الموافقات', 'अनुमोदन कार्यक्षेत्र'], 'CHAT': ['الدردشة', 'चैट'],
        'Profile': ['الملف الشخصي', 'प्रोफ़ाइल'], 'Notifications': ['الإشعارات', 'सूचनाएँ'], 'Logout': ['تسجيل الخروج', 'लॉग आउट'],
        'Language': ['اللغة', 'भाषा'], 'English': ['الإنجليزية', 'अंग्रेज़ी'], 'Arabic': ['العربية', 'अरबी'], 'Hindi': ['الهندية', 'हिन्दी'],
        'Search': ['بحث', 'खोजें'], 'Search complaints': ['البحث في الشكاوى', 'शिकायतें खोजें'],
        'Search complaints...': ['ابحث في الشكاوى...', 'शिकायतें खोजें...'], 'Clear search': ['مسح البحث', 'खोज साफ़ करें'],
        'Search this keyword in': ['ابحث عن هذه الكلمة في', 'इस शब्द को इसमें खोजें'], 'All Fields': ['كل الحقول', 'सभी फ़ील्ड'],
        'All Columns': ['كل الأعمدة', 'सभी कॉलम'], 'Actions': ['الإجراءات', 'कार्रवाइयाँ'], 'Action': ['إجراء', 'कार्रवाई'],
        'View': ['عرض', 'देखें'], 'Edit': ['تعديل', 'संपादित करें'], 'Delete': ['حذف', 'हटाएँ'], 'Save': ['حفظ', 'सहेजें'],
        'Save Changes': ['حفظ التغييرات', 'बदलाव सहेजें'], 'Cancel': ['إلغاء', 'रद्द करें'], 'Clear': ['مسح', 'साफ़ करें'],
        'Close': ['إغلاق', 'बंद करें'], 'Next': ['التالي', 'अगला'], 'Prev': ['السابق', 'पिछला'], 'First': ['الأول', 'पहला'], 'Last': ['الأخير', 'अंतिम'],
        'Submit': ['إرسال', 'जमा करें'], 'Upload': ['رفع', 'अपलोड'], 'Click to upload': ['انقر للرفع', 'अपलोड करने के लिए क्लिक करें'],
        'or drag and drop': ['أو اسحب وأفلت', 'या खींचकर छोड़ें'], 'Loading...': ['جارٍ التحميل...', 'लोड हो रहा है...'],
        'Creating': ['جارٍ الإنشاء', 'बनाया जा रहा है'], 'Saving': ['جارٍ الحفظ', 'सहेजा जा रहा है'],

        'PATTERN COMPLAINT': ['شكوى النمط', 'पैटर्न शिकायत'], 'PRODUCTION COMPLAINT': ['شكوى الإنتاج', 'उत्पादन शिकायत'],
        'QUALITY COMPLAINT': ['شكوى الجودة', 'गुणवत्ता शिकायत'], 'FACTORY COMPLAINT': ['شكوى المصنع', 'फैक्टरी शिकायत'],
        'Pattern Complaint': ['شكوى النمط', 'पैटर्न शिकायत'], 'Production Complaint': ['شكوى الإنتاج', 'उत्पादन शिकायत'],
        'Quality Complaint': ['شكوى الجودة', 'गुणवत्ता शिकायत'], 'Factory Complaint': ['شكوى المصنع', 'फैक्टरी शिकायत'],
        'Pattern Complaint Type': ['نوع شكوى النمط', 'पैटर्न शिकायत प्रकार'],
        'Production Complaint Type': ['نوع شكوى الإنتاج', 'उत्पादन शिकायत प्रकार'],
        'Quality Complaint Type': ['نوع شكوى الجودة', 'गुणवत्ता शिकायत प्रकार'],
        'Factory Complaint Type': ['نوع شكوى المصنع', 'फैक्टरी शिकायत प्रकार'],
        'Pattern': ['النمط', 'पैटर्न'], 'Production': ['الإنتاج', 'उत्पादन'], 'Quality': ['الجودة', 'गुणवत्ता'], 'Factory': ['المصنع', 'फैक्टरी'],
        'Complaint Types': ['أنواع الشكاوى', 'शिकायत के प्रकार'], 'Vehicle Models': ['طرازات المركبات', 'वाहन मॉडल'],
        'SKU Items': ['عناصر رمز المنتج', 'एसकेयू आइटम'],
        'Add New Complaint': ['إضافة شكوى جديدة', 'नई शिकायत जोड़ें'],
        'Complaint Management': ['إدارة الشكاوى', 'शिकायत प्रबंधन'],
        'Save Pattern Complaint': ['حفظ شكوى النمط', 'पैटर्न शिकायत सहेजें'],
        'Save Production Complaint': ['حفظ شكوى الإنتاج', 'उत्पादन शिकायत सहेजें'],
        'Save Quality Complaint': ['حفظ شكوى الجودة', 'गुणवत्ता शिकायत सहेजें'],
        'Save Factory Complaint': ['حفظ شكوى المصنع', 'फैक्टरी शिकायत सहेजें'],
        'Register a new customer complaint with detailed information': ['سجّل شكوى عميل جديدة بمعلومات مفصلة', 'विस्तृत जानकारी के साथ नई ग्राहक शिकायत दर्ज करें'],
        'Complaint Details': ['تفاصيل الشكوى', 'शिकायत विवरण'], 'Complaint details': ['تفاصيل الشكوى', 'शिकायत विवरण'],
        'Complaint Description': ['وصف الشكوى', 'शिकायत का विवरण'], 'Complaint description': ['وصف الشكوى', 'शिकायत का विवरण'],
        'Complaint ID': ['رقم الشكوى', 'शिकायत आईडी'], 'Complaint type': ['نوع الشكوى', 'शिकायत का प्रकार'],
        'Complaint Journey': ['مسار الشكوى', 'शिकायत यात्रा'], 'Complaint Media': ['وسائط الشكوى', 'शिकायत मीडिया'],
        'Product and source': ['المنتج والمصدر', 'उत्पाद और स्रोत'], 'Product & Source': ['المنتج والمصدر', 'उत्पाद और स्रोत'],
        'Images and videos': ['الصور ومقاطع الفيديو', 'चित्र और वीडियो'], 'Media Files': ['ملفات الوسائط', 'मीडिया फ़ाइलें'],
        'No media attached': ['لا توجد وسائط مرفقة', 'कोई मीडिया संलग्न नहीं'], 'Open attached file': ['فتح الملف المرفق', 'संलग्न फ़ाइल खोलें'],
        'Play video': ['تشغيل الفيديو', 'वीडियो चलाएँ'], 'Image Preview': ['معاينة الصورة', 'चित्र पूर्वावलोकन'],
        'Date': ['التاريخ', 'तारीख'], 'Report date': ['تاريخ البلاغ', 'रिपोर्ट की तारीख'], 'Report status': ['حالة البلاغ', 'रिपोर्ट स्थिति'],
        'Reported By': ['أبلغ بواسطة', 'रिपोर्टकर्ता'], 'Reported by': ['أبلغ بواسطة', 'रिपोर्टकर्ता'], 'Created by': ['أنشأ بواسطة', 'निर्माता'],
        'Country': ['الدولة', 'देश'], 'Channel': ['القناة', 'चैनल'], 'Priority': ['الأولوية', 'प्राथमिकता'],
        'Type': ['النوع', 'प्रकार'], 'Description': ['الوصف', 'विवरण'], 'Material': ['المادة', 'सामग्री'], 'Series': ['السلسلة', 'सीरीज़'],
        'Brand': ['العلامة التجارية', 'ब्रांड'], 'Model': ['الطراز', 'मॉडल'], 'Submodel': ['الطراز الفرعي', 'सब-मॉडल'],
        'Sub-Model': ['الطراز الفرعي', 'सब-मॉडल'], 'Year': ['السنة', 'वर्ष'], 'Year Range': ['نطاق السنوات', 'वर्ष सीमा'],
        'Vehicle Information': ['معلومات المركبة', 'वाहन जानकारी'], 'Select Brand': ['اختر العلامة التجارية', 'ब्रांड चुनें'],
        'Select Model': ['اختر الطراز', 'मॉडल चुनें'], 'Select Sub-Model (Optional)': ['اختر الطراز الفرعي (اختياري)', 'सब-मॉडल चुनें (वैकल्पिक)'],
        'Select Year': ['اختر السنة', 'वर्ष चुनें'], 'Select SKU': ['اختر رمز المنتج', 'एसकेयू चुनें'], 'Select Type': ['اختر النوع', 'प्रकार चुनें'],
        'Select Country': ['اختر الدولة', 'देश चुनें'], 'Update Order #': ['رقم أمر التحديث', 'अपडेट ऑर्डर संख्या'],
        'Updated Order #': ['رقم الأمر المحدّث', 'अपडेटेड ऑर्डर संख्या'], 'Batch / Order #': ['رقم الدفعة / الطلب', 'बैच / ऑर्डर संख्या'],
        'Batch order': ['أمر الدفعة', 'बैच ऑर्डर'], 'Phone Number': ['رقم الهاتف', 'फ़ोन नंबर'],
        'First Name': ['الاسم الأول', 'पहला नाम'], 'Last Name': ['اسم العائلة', 'अंतिम नाम'], 'Email': ['البريد الإلكتروني', 'ईमेल'],

        'Status': ['الحالة', 'स्थिति'], 'OPEN': ['مفتوحة', 'खुली'], 'Submitted': ['تم الإرسال', 'जमा'],
        'Assigned to Factory': ['مُسندة إلى المصنع', 'फैक्टरी को सौंपा गया'], 'Factory Review': ['مراجعة المصنع', 'फैक्टरी समीक्षा'],
        'Awaiting Approval': ['بانتظار الموافقة', 'अनुमोदन की प्रतीक्षा'], 'Partially Approved': ['موافق عليها جزئياً', 'आंशिक अनुमोदन'],
        'Rework Required': ['إعادة العمل مطلوبة', 'पुनःकार्य आवश्यक'], 'Approved': ['موافق عليها', 'अनुमोदित'],
        'Action In Progress': ['الإجراء قيد التنفيذ', 'कार्रवाई जारी'], 'Awaiting Execution Verification': ['بانتظار التحقق من التنفيذ', 'निष्पादन सत्यापन की प्रतीक्षा'],
        'Execution Partially Verified': ['تم التحقق من التنفيذ جزئياً', 'निष्पादन आंशिक सत्यापित'],
        'Pending Final Update': ['بانتظار التحديث النهائي', 'अंतिम अपडेट लंबित'], 'Closed': ['مغلقة', 'बंद'], 'On Hold': ['معلّقة', 'होल्ड पर'],
        'Low': ['منخفضة', 'निम्न'], 'Medium': ['متوسطة', 'मध्यम'], 'Top': ['عليا', 'शीर्ष'],
        'Low Priority': ['أولوية منخفضة', 'निम्न प्राथमिकता'], 'Medium Priority': ['أولوية متوسطة', 'मध्यम प्राथमिकता'], 'Top Priority': ['أولوية عليا', 'शीर्ष प्राथमिकता'],
        'All Statuses': ['كل الحالات', 'सभी स्थितियाँ'], 'All Priorities': ['كل الأولويات', 'सभी प्राथमिकताएँ'],
        'All Countries': ['كل الدول', 'सभी देश'], 'All Complaint Types': ['كل أنواع الشكاوى', 'सभी शिकायत प्रकार'],
        'All Channels': ['كل القنوات', 'सभी चैनल'], 'All Reporters': ['كل المبلّغين', 'सभी रिपोर्टकर्ता'],
        'All Types': ['كل الأنواع', 'सभी प्रकार'], 'No complaints found': ['لم يتم العثور على شكاوى', 'कोई शिकायत नहीं मिली'],
        'Try adjusting your filters or add a new complaint to get started.': ['جرّب تعديل عوامل التصفية أو أضف شكوى جديدة للبدء.', 'फ़िल्टर बदलें या शुरू करने के लिए नई शिकायत जोड़ें।'],

        'Workflow Journey': ['مسار سير العمل', 'कार्यप्रवाह यात्रा'], 'Approval': ['الموافقة', 'अनुमोदन'],
        'Action Plan': ['خطة العمل', 'कार्य योजना'], 'Action plan': ['خطة العمل', 'कार्य योजना'], 'Action Execution': ['تنفيذ الإجراء', 'कार्रवाई निष्पादन'],
        'Verification': ['التحقق', 'सत्यापन'], 'Final Update': ['التحديث النهائي', 'अंतिम अपडेट'],
        'Factory Reason': ['سبب المصنع', 'फैक्टरी कारण'], 'Root cause': ['السبب الجذري', 'मूल कारण'],
        'Factory Action Plan': ['خطة عمل المصنع', 'फैक्टरी कार्य योजना'], 'Proposed Factory Action Plan': ['خطة عمل المصنع المقترحة', 'प्रस्तावित फैक्टरी कार्य योजना'],
        'Factory Priority': ['أولوية المصنع', 'फैक्टरी प्राथमिकता'], 'Factory response': ['رد المصنع', 'फैक्टरी प्रतिक्रिया'],
        'Factory executive': ['مسؤول المصنع', 'फैक्टरी कार्यकारी'], 'Execution notes': ['ملاحظات التنفيذ', 'निष्पादन टिप्पणियाँ'],
        'CAD updated date': ['تاريخ تحديث CAD', 'CAD अपडेट तारीख'], 'Container number': ['رقم الحاوية', 'कंटेनर संख्या'],
        'Closed at': ['أُغلقت في', 'बंद होने का समय'], 'Closed by': ['أُغلقت بواسطة', 'बंद करने वाला'],
        'Approval history': ['سجل الموافقات', 'अनुमोदन इतिहास'], 'Activity': ['النشاط', 'गतिविधि'],
        'Approval Inbox': ['صندوق الموافقات', 'अनुमोदन इनबॉक्स'], 'Live Approver Status Matrix': ['مصفوفة حالة الموافقين المباشرة', 'लाइव अनुमोदक स्थिति मैट्रिक्स'],
        'Parallel Review Progress': ['تقدم المراجعة المتوازية', 'समानांतर समीक्षा प्रगति'], 'Submit Your Opinion': ['أرسل رأيك', 'अपनी राय जमा करें'],
        'Approve Plan': ['الموافقة على الخطة', 'योजना अनुमोदित करें'], 'Reject / Rework': ['رفض / إعادة العمل', 'अस्वीकार / पुनःकार्य'],
        'Green light proposed action': ['إعطاء الضوء الأخضر للإجراء المقترح', 'प्रस्तावित कार्रवाई को हरी झंडी दें'],
        'Request revisions or reject': ['اطلب تعديلات أو ارفض', 'संशोधन माँगें या अस्वीकार करें'],
        'Submit Approval Decision': ['إرسال قرار الموافقة', 'अनुमोदन निर्णय जमा करें'],
        'No Approvals Found': ['لم يتم العثور على موافقات', 'कोई अनुमोदन नहीं मिला'], 'No reviews waiting': ['لا توجد مراجعات منتظرة', 'कोई समीक्षा लंबित नहीं'],
        'No decisions submitted yet.': ['لم تُرسل قرارات بعد.', 'अभी कोई निर्णय जमा नहीं हुआ।'],

        'Vehicle Management': ['إدارة المركبات', 'वाहन प्रबंधन'], 'Brand Logo': ['شعار العلامة التجارية', 'ब्रांड लोगो'],
        'Brand Name': ['اسم العلامة التجارية', 'ब्रांड नाम'], 'Model Name': ['اسم الطراز', 'मॉडल नाम'],
        'Sub-Model Name (Optional)': ['اسم الطراز الفرعي (اختياري)', 'सब-मॉडल नाम (वैकल्पिक)'],
        'Layout Code': ['رمز التخطيط', 'लेआउट कोड'], 'Number of Seats': ['عدد المقاعد', 'सीटों की संख्या'],
        'Number of Doors': ['عدد الأبواب', 'दरवाज़ों की संख्या'], 'Seats': ['المقاعد', 'सीटें'], 'Doors': ['الأبواب', 'दरवाज़े'],
        'Vehicle Country': ['دولة المركبة', 'वाहन देश'], 'Measurement Country': ['دولة القياس', 'मापन देश'],
        'No vehicles added yet': ['لم تتم إضافة مركبات بعد', 'अभी कोई वाहन नहीं जोड़ा गया'],
        'Add your first vehicle using the form on the left or upload a CSV file.': ['أضف مركبتك الأولى باستخدام النموذج أو ارفع ملف CSV.', 'फ़ॉर्म से अपना पहला वाहन जोड़ें या CSV फ़ाइल अपलोड करें।'],
        'SKU Management': ['إدارة رموز المنتجات', 'एसकेयू प्रबंधन'], 'SKU Code': ['رمز المنتج', 'एसकेयू कोड'],
        'Region': ['المنطقة', 'क्षेत्र'], 'Upload CSV': ['رفع ملف CSV', 'CSV अपलोड करें'], 'No values found': ['لم يتم العثور على قيم', 'कोई मान नहीं मिला'],

        'Master Settings': ['الإعدادات الرئيسية', 'मास्टर सेटिंग्स'], 'Manage Master Settings': ['إدارة الإعدادات الرئيسية', 'मास्टर सेटिंग्स प्रबंधित करें'],
        'Configure master data including channels, countries, and case categories': ['إدارة البيانات الرئيسية، بما فيها القنوات والدول وفئات الشكاوى', 'चैनल, देश और शिकायत श्रेणियों सहित मास्टर डेटा व्यवस्थित करें'],
        'Add New Setting': ['إضافة إعداد جديد', 'नई सेटिंग जोड़ें'], 'Current Settings': ['الإعدادات الحالية', 'वर्तमान सेटिंग्स'],
        'Category': ['الفئة', 'श्रेणी'], 'Name': ['الاسم', 'नाम'], 'Add Setting': ['إضافة الإعداد', 'सेटिंग जोड़ें'],
        'Edit Master Setting': ['تعديل الإعداد الرئيسي', 'मास्टर सेटिंग संपादित करें'], 'Update Setting': ['تحديث الإعداد', 'सेटिंग अपडेट करें'],
        'No settings for this category': ['لا توجد إعدادات لهذه الفئة', 'इस श्रेणी में कोई सेटिंग नहीं है'],
        'Setting updated successfully!': ['تم تحديث الإعداد بنجاح!', 'सेटिंग सफलतापूर्वक अपडेट हुई!'],
        'WhatsApp': ['واتساب', 'व्हाट्सऐप'], 'Stitching': ['الخياطة', 'सिलाई'], 'Heavy': ['ثقيل', 'भारी'],
        'User': ['المستخدم', 'उपयोगकर्ता'], 'Users': ['المستخدمون', 'उपयोगकर्ता'], 'Username': ['اسم المستخدم', 'उपयोगकर्ता नाम'],
        'Username *': ['اسم المستخدم *', 'उपयोगकर्ता नाम *'], 'Email Address *': ['عنوان البريد الإلكتروني *', 'ईमेल पता *'],
        'Password': ['كلمة المرور', 'पासवर्ड'], 'Password *': ['كلمة المرور *', 'पासवर्ड *'], 'Reset Password': ['إعادة تعيين كلمة المرور', 'पासवर्ड रीसेट करें'],
        'Role': ['الدور', 'भूमिका'], 'Workflow Role *': ['دور سير العمل *', 'कार्यप्रवाह भूमिका *'], 'Assigned Country': ['الدولة المعيّنة', 'निर्धारित देश'],
        'Department': ['القسم', 'विभाग'], 'Profile Photo': ['صورة الملف الشخصي', 'प्रोफ़ाइल फ़ोटो'], 'Update Profile Photo': ['تحديث صورة الملف الشخصي', 'प्रोफ़ाइल फ़ोटो अपडेट करें'],
        'Create User': ['إنشاء مستخدم', 'उपयोगकर्ता बनाएँ'], 'Create New User': ['إنشاء مستخدم جديد', 'नया उपयोगकर्ता बनाएँ'],
        'Delete User': ['حذف المستخدم', 'उपयोगकर्ता हटाएँ'], 'Admin': ['المشرف', 'एडमिन'], 'Staff': ['موظف', 'स्टाफ'], 'Superuser': ['مستخدم متميز', 'सुपरयूज़र'],
        'Country Executive': ['مسؤول الدولة', 'देश कार्यकारी'], 'Factory Executive': ['مسؤول المصنع', 'फैक्टरी कार्यकारी'], 'Factory Complaint Registrar': ['مسجل شكاوى المصنع', 'फैक्टरी शिकायत पंजीयक'], 'Factory Viewer': ['مراقب المصنع', 'फैक्टरी दर्शक'],
        'Active Sessions': ['الجلسات النشطة', 'सक्रिय सत्र'], 'Active Users Online': ['المستخدمون النشطون الآن', 'ऑनलाइन सक्रिय उपयोगकर्ता'],
        'Login Time': ['وقت تسجيل الدخول', 'लॉगिन समय'], 'IP Address': ['عنوان IP', 'आईपी पता'], 'Terminate': ['إنهاء', 'समाप्त करें'],
        'No active sessions.': ['لا توجد جلسات نشطة.', 'कोई सक्रिय सत्र नहीं।'], 'Audit & Activity Logs': ['سجلات التدقيق والنشاط', 'ऑडिट और गतिविधि लॉग'],
        'Timestamp': ['الطابع الزمني', 'समय-मुद्रा'], 'Object Type': ['نوع العنصر', 'ऑब्जेक्ट प्रकार'], 'Object Detail': ['تفاصيل العنصر', 'ऑब्जेक्ट विवरण'],
        'No activity logs found.': ['لم يتم العثور على سجلات نشاط.', 'कोई गतिविधि लॉग नहीं मिला।'],
        'Total Users': ['إجمالي المستخدمين', 'कुल उपयोगकर्ता'], 'Total Complaints': ['إجمالي الشكاوى', 'कुल शिकायतें'],
        'Complaints Resolved': ['الشكاوى المحلولة', 'समाधान की गई शिकायतें'], 'Active Workflow': ['سير العمل النشط', 'सक्रिय कार्यप्रवाह'],
        'Manage Catalog': ['إدارة الدليل', 'कैटलॉग प्रबंधित करें'], 'Vehicle Brands & Models': ['علامات وطرازات المركبات', 'वाहन ब्रांड और मॉडल'],
        'SKU Master Catalog': ['الدليل الرئيسي لرموز المنتجات', 'एसकेयू मास्टर कैटलॉग'],

        'Chat Workspace': ['مساحة عمل الدردشة', 'चैट कार्यक्षेत्र'], 'Select a Team Member': ['اختر عضوًا في الفريق', 'टीम सदस्य चुनें'],
        'No messages yet': ['لا توجد رسائل بعد', 'अभी कोई संदेश नहीं'], 'Send': ['إرسال', 'भेजें'],
        'Login': ['تسجيل الدخول', 'लॉगिन'], 'Sign In': ['تسجيل الدخول', 'साइन इन'], 'Remember me': ['تذكرني', 'मुझे याद रखें'],
        'Forgot password?': ['هل نسيت كلمة المرور؟', 'पासवर्ड भूल गए?'],
        'Delete Complaint': ['حذف الشكوى', 'शिकायत हटाएँ'], 'Are you sure you want to delete this complaint?': ['هل أنت متأكد أنك تريد حذف هذه الشكوى؟', 'क्या आप वाकई यह शिकायत हटाना चाहते हैं?'],
        'Yes, delete': ['نعم، احذف', 'हाँ, हटाएँ'], 'Success': ['تم بنجاح', 'सफल'], 'Error': ['خطأ', 'त्रुटि'], 'Warning': ['تحذير', 'चेतावनी'],
        'Vehicle added successfully!': ['تمت إضافة المركبة بنجاح!', 'वाहन सफलतापूर्वक जोड़ा गया!'],
        'Vehicle deleted successfully!': ['تم حذف المركبة بنجاح!', 'वाहन सफलतापूर्वक हटाया गया!'],
        'Vehicle updated successfully!': ['تم تحديث المركبة بنجاح!', 'वाहन सफलतापूर्वक अपडेट किया गया!'],
        'Complaint deleted successfully.': ['تم حذف الشكوى بنجاح.', 'शिकायत सफलतापूर्वक हटाई गई।'],
        'Factory review submitted for approval.': ['تم إرسال مراجعة المصنع للموافقة.', 'फैक्टरी समीक्षा अनुमोदन के लिए जमा की गई।'],
        'All required members approved. The executive has received the green light.': ['وافق جميع الأعضاء المطلوبين. تلقى المسؤول الضوء الأخضر.', 'सभी आवश्यक सदस्यों ने अनुमोदन दिया। कार्यकारी को हरी झंडी मिल गई है।'],
        'Execution was verified unanimously. Final CAD and container updates are now unlocked.': ['تم التحقق من التنفيذ بالإجماع. أصبحت تحديثات CAD والحاوية النهائية متاحة الآن.', 'निष्पादन सर्वसम्मति से सत्यापित हुआ। अंतिम CAD और कंटेनर अपडेट अब उपलब्ध हैं।'],
        'Execution correction was requested and the case returned to the Factory Executive.': ['طُلب تصحيح التنفيذ وأُعيدت الحالة إلى مسؤول المصنع.', 'निष्पादन सुधार माँगा गया और मामला फैक्टरी कार्यकारी को लौटाया गया।'],
        'Action plan started. Submit the execution for verification when implementation is complete.': ['بدأت خطة العمل. أرسل التنفيذ للتحقق عند اكتمال التطبيق.', 'कार्य योजना शुरू हुई। कार्यान्वयन पूरा होने पर निष्पादन सत्यापन के लिए जमा करें।'],
        'Execution submitted to the original approvers for verification.': ['تم إرسال التنفيذ إلى الموافقين الأصليين للتحقق.', 'निष्पादन सत्यापन के लिए मूल अनुमोदकों को भेजा गया।'],
        'Final updates saved. The complaint is now closed.': ['تم حفظ التحديثات النهائية. الشكوى مغلقة الآن.', 'अंतिम अपडेट सहेजे गए। शिकायत अब बंद है।'],
        'All notifications marked as read.': ['تم تعليم جميع الإشعارات كمقروءة.', 'सभी सूचनाएँ पढ़ी हुई चिह्नित की गईं।'],
        'Your profile details have been updated successfully.': ['تم تحديث تفاصيل ملفك الشخصي بنجاح.', 'आपकी प्रोफ़ाइल जानकारी सफलतापूर्वक अपडेट हुई।'],
        'Your password has been changed successfully.': ['تم تغيير كلمة المرور بنجاح.', 'आपका पासवर्ड सफलतापूर्वक बदल गया।'],
        'Session terminated successfully.': ['تم إنهاء الجلسة بنجاح.', 'सत्र सफलतापूर्वक समाप्त हुआ।'],
        'This page is restricted to administrators only.': ['هذه الصفحة مخصصة للمشرفين فقط.', 'यह पृष्ठ केवल प्रशासकों के लिए है।'],
        'You are not allowed to review this complaint.': ['غير مسموح لك بمراجعة هذه الشكوى.', 'आपको इस शिकायत की समीक्षा की अनुमति नहीं है।'],
        'This complaint is not ready for factory review.': ['هذه الشكوى غير جاهزة لمراجعة المصنع.', 'यह शिकायत फैक्टरी समीक्षा के लिए तैयार नहीं है।']
    };

    const languageIndex = language === 'ar' ? 0 : 1;
    const exact = new Map();
    Object.entries(translations).forEach(([english, values]) => {
        exact.set(english.replace(/\s+/g, ' ').trim().toLocaleLowerCase('en'), values[languageIndex]);
    });
    const skipped = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'CODE', 'PRE', 'TEXTAREA']);
    const attributes = ['placeholder', 'title', 'aria-label'];
    const prefixTranslations = language === 'ar' ? [
        ['Reported by ', 'أبلغ بواسطة '], ['Page ', 'الصفحة '], ['Round ', 'الجولة '],
        ['Country: ', 'الدولة: '], ['Factory: ', 'المصنع: '], ['Vehicle: ', 'المركبة: '], ['SKU: ', 'رمز المنتج: ']
    ] : [
        ['Reported by ', 'रिपोर्टकर्ता '], ['Page ', 'पृष्ठ '], ['Round ', 'दौर '],
        ['Country: ', 'देश: '], ['Factory: ', 'फैक्टरी: '], ['Vehicle: ', 'वाहन: '], ['SKU: ', 'एसकेयू: ']
    ];

    function translateValue(value) {
        if (!value) return value;
        const leading = value.match(/^\s*/)[0];
        const trailing = value.match(/\s*$/)[0];
        const normalized = value.replace(/\s+/g, ' ').trim();
        let translated = exact.get(normalized.toLocaleLowerCase('en'));
        if (!translated && normalized.endsWith(':')) {
            const base = normalized.slice(0, -1).trim();
            const translatedBase = exact.get(base.toLocaleLowerCase('en'));
            if (translatedBase) translated = translatedBase + ':';
        }
        if (!translated && normalized.endsWith(' - Fabro Leather')) {
            const base = normalized.slice(0, -' - Fabro Leather'.length).trim();
            const translatedBase = exact.get(base.toLocaleLowerCase('en'));
            if (translatedBase) translated = translatedBase + ' - Fabro Leather';
        }
        if (!translated) {
            for (const [englishPrefix, translatedPrefix] of prefixTranslations) {
                if (normalized.startsWith(englishPrefix)) {
                    translated = translatedPrefix + normalized.slice(englishPrefix.length);
                    break;
                }
            }
        }
        return translated ? leading + translated + trailing : value;
    }

    function translateElement(element) {
        if (!(element instanceof Element) || element.closest('[data-i18n-skip]')) return;
        attributes.forEach((attribute) => {
            if (element.hasAttribute(attribute)) {
                element.setAttribute(attribute, translateValue(element.getAttribute(attribute)));
            }
        });
        if (element.tagName === 'OPTION') {
            element.textContent = translateValue(element.textContent);
        }
    }

    function translateTree(container) {
        if (!container) return;
        if (container.nodeType === Node.ELEMENT_NODE) translateElement(container);
        const walker = document.createTreeWalker(container, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
            acceptNode(node) {
                const parent = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
                if (!parent || skipped.has(parent.tagName) || parent.closest('[data-i18n-skip]')) return NodeFilter.FILTER_REJECT;
                return NodeFilter.FILTER_ACCEPT;
            }
        });
        let node;
        while ((node = walker.nextNode())) {
            if (node.nodeType === Node.TEXT_NODE) node.nodeValue = translateValue(node.nodeValue);
            else translateElement(node);
        }
    }

    function run() {
        translateTree(document.body);
        document.title = translateValue(document.title);
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run, { once: true });
    else run();

    document.addEventListener('htmx:afterSwap', (event) => translateTree(event.detail && event.detail.target));
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => mutation.addedNodes.forEach((node) => {
            if (node.nodeType === Node.TEXT_NODE) node.nodeValue = translateValue(node.nodeValue);
            else if (node.nodeType === Node.ELEMENT_NODE) translateTree(node);
        }));
    });
    const beginObserving = () => observer.observe(document.body, { childList: true, subtree: true });
    if (document.body) beginObserving();
    else document.addEventListener('DOMContentLoaded', beginObserving, { once: true });
}());
