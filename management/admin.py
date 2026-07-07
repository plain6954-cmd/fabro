from django.contrib import admin
from .models import Brand, Model, SubModel, YearRange, SKU, MasterSetting, Complaint, ComplaintMedia
from django.contrib.sessions.models import Session
from django.contrib import admin
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models import Q


admin.site.register(Session)
admin.site.register(MasterSetting)
admin.site.register(SKU)
admin.site.register(Complaint)
admin.site.register(ComplaintMedia)
admin.site.register(Brand)
admin.site.register(Model)
admin.site.register(SubModel)
admin.site.register(YearRange)
