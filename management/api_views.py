from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated, SAFE_METHODS
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.authtoken.models import Token
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView
from django.contrib.auth import authenticate
from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from .serializers import (
    ApprovalDecisionInputSerializer,
    ComplaintApprovalSerializer,
    ComplaintSerializer,
    DashboardStatsSerializer,
    FactoryReviewInputSerializer,
    FinalComplaintUpdateSerializer,
    NotificationSerializer,
    UserSerializer,
    RegisterSerializer,
    UserProfileUpdateSerializer,
)
from .models import (
    Complaint,
    ComplaintApproval,
    ComplaintTypes,
    Notification,
    YearRange,
    SKU,
    MasterSetting,
    WorkflowRoles,
    WorkflowStatuses,
    infer_complaint_type,
)
from .services.workflow import (
    REPORT_EDITABLE_FIELDS,
    approval_progress,
    can_user_create_complaint,
    can_user_manage_catalog,
    close_complaint_after_execution,
    initialize_created_complaint,
    is_country_executive,
    is_workflow_admin,
    can_user_edit_report_step,
    get_user_profile,
    record_approval_decision,
    record_report_edit,
    start_action_execution,
    submit_factory_review,
    visible_complaints_for_user,
)


class IsCatalogAdminOrReadOnly(BasePermission):
    """Allow authenticated reads, but restrict catalog writes to staff/admins."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return can_user_manage_catalog(request.user)

class LoginAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

    def post(self, request, *args, **kwargs):
        username = request.data.get('username')
        password = request.data.get('password')
        if not username or not password:
            return Response(
                {'error': 'Please provide both username and password.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        user = authenticate(username=username, password=password)
        if not user:
            return Response(
                {'error': 'Invalid credentials.'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        token, created = Token.objects.get_or_create(user=user)
        return Response({
            'token': token.key,
            'user': UserSerializer(user).data
        }, status=status.HTTP_200_OK)

class LogoutAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            request.user.auth_token.delete()
            return Response({'message': 'Successfully logged out.'}, status=status.HTTP_200_OK)
        except Token.DoesNotExist:
            return Response({'error': 'Token does not exist or user already logged out.'}, status=status.HTTP_400_BAD_REQUEST)

class RegisterAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        if not settings.ALLOW_PUBLIC_REGISTRATION:
            return Response(
                {'error': 'Public registration is disabled. Ask an administrator to create your account.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            token, created = Token.objects.get_or_create(user=user)
            return Response({
                'token': token.key,
                'user': UserSerializer(user).data
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserProfileAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        return Response(UserSerializer(request.user).data, status=status.HTTP_200_OK)

    def patch(self, request, *args, **kwargs):
        serializer = UserProfileUpdateSerializer(
            request.user,
            data=request.data,
            partial=True
        )
        if serializer.is_valid():
            serializer.save()
            return Response(UserSerializer(request.user).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class DashboardAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        visible_complaints = visible_complaints_for_user(request.user, Complaint.objects.all())
        complaint_status_counts = dict(
            visible_complaints.values_list('status').annotate(count=Count('status'))
        )
        data = {
            'total_complaints': sum(complaint_status_counts.values()),
            'open_complaints': complaint_status_counts.get('Open', 0),
            'closed_complaints': complaint_status_counts.get('Closed', 0),
            'on_hold_complaints': complaint_status_counts.get('On Hold', 0),
            'total_vehicles': YearRange.objects.count(),
            'total_skus': SKU.objects.count(),
            'total_settings': MasterSetting.objects.count(),
            'total_master_settings': MasterSetting.objects.count(),
        }
        return Response(DashboardStatsSerializer(data).data, status=status.HTTP_200_OK)

from .serializers import SKUSerializer, YearRangeSerializer

class ComplaintListCreateAPIView(ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ComplaintSerializer

    def get_queryset(self):
        return visible_complaints_for_user(
            self.request.user,
            Complaint.objects.select_related(
                'channel', 'country', 'person', 'case_sub_category',
                'series', 'material', 'sku', 'brand', 'model', 'sub_model', 'year',
                'created_by', 'assigned_factory_executive', 'closed_by',
            ).prefetch_related(
                'media_files',
                'approvals__approver_user',
                'timeline_events__user',
            ).all().order_by('-complaint_id')
        )

    @transaction.atomic
    def perform_create(self, serializer):
        if not can_user_create_complaint(self.request.user):
            raise PermissionDenied('Your role can view complaints but cannot create them.')
        case_type = serializer.validated_data.get('case_sub_category')
        complaint_type = serializer.validated_data.get('complaint_type') or infer_complaint_type(
            case_type.name if case_type else ''
        )
        create_values = {
            'created_by': self.request.user,
            'complaint_type': complaint_type,
            'workflow_status': WorkflowStatuses.SUBMITTED,
            'date': timezone.localdate(),
        }
        if is_country_executive(self.request.user):
            profile = get_user_profile(self.request.user)
            if not profile or not profile.country_id:
                raise PermissionDenied('Your account must be assigned to a country before reporting complaints.')
            if complaint_type == ComplaintTypes.LINE:
                raise PermissionDenied('Country executives cannot create line complaints.')
            create_values['country'] = profile.country
        complaint = serializer.save(
            **create_values,
        )
        initialize_created_complaint(complaint, self.request.user)

class ComplaintRetrieveUpdateDestroyAPIView(RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ComplaintSerializer
    lookup_field = 'complaint_id'

    def get_queryset(self):
        return visible_complaints_for_user(self.request.user, Complaint.objects.all())

    def perform_update(self, serializer):
        complaint = self.get_object()
        if not can_user_edit_report_step(self.request.user, complaint):
            raise PermissionDenied('You are not allowed to edit this complaint at its current workflow step.')
        tracked_fields = {
            field_name: getattr(complaint, field_name)
            for field_name in serializer.validated_data
            if field_name in REPORT_EDITABLE_FIELDS
        }
        complaint = serializer.save(
            country=complaint.country,
            case_sub_category=complaint.case_sub_category,
            complaint_type=complaint.complaint_type,
        )
        record_report_edit(
            complaint,
            self.request.user,
            changes={
                field_name: (old_value, getattr(complaint, field_name))
                for field_name, old_value in tracked_fields.items()
            },
        )

    def perform_destroy(self, instance):
        if not is_workflow_admin(self.request.user):
            raise PermissionDenied('Only workflow administrators can delete complaints.')
        instance.delete()


class FactoryReviewAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, complaint_id, *args, **kwargs):
        complaint = visible_complaints_for_user(request.user, Complaint.objects.all()).filter(
            complaint_id=complaint_id,
        ).first()
        if not complaint:
            return Response({'error': 'Complaint not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = FactoryReviewInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            approvals = submit_factory_review(
                complaint,
                request.user,
                serializer.validated_data['factory_reason'],
                serializer.validated_data['factory_action_plan'],
                serializer.validated_data['factory_priority'],
            )
        except PermissionError as exc:
            raise PermissionDenied(str(exc)) from exc
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'complaint': ComplaintSerializer(complaint).data,
            'approvals': ComplaintApprovalSerializer(approvals, many=True).data,
        }, status=status.HTTP_200_OK)


class ApprovalInboxAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        profile = get_user_profile(request.user)
        if not profile or profile.role != WorkflowRoles.APPROVER:
            raise PermissionDenied('Only configured approvers can access the approval inbox.')

        approvals = ComplaintApproval.objects.filter(
            approver_user=request.user,
            complaint__workflow_status__in=[
                WorkflowStatuses.AWAITING_APPROVAL,
                WorkflowStatuses.PARTIALLY_APPROVED,
            ],
        ).select_related('complaint', 'approver_user').order_by('-created_at')
        current = [
            approval for approval in approvals
            if approval.approval_round == approval_progress(approval.complaint)['round']
        ]
        return Response(ComplaintApprovalSerializer(current, many=True).data)


class ApprovalDecisionAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, approval_id, *args, **kwargs):
        serializer = ApprovalDecisionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            approval, outcome = record_approval_decision(
                approval_id,
                request.user,
                serializer.validated_data['decision'],
                serializer.validated_data.get('comment', ''),
            )
        except PermissionError as exc:
            raise PermissionDenied(str(exc)) from exc
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'outcome': outcome,
            'approval': ComplaintApprovalSerializer(approval).data,
            'complaint': ComplaintSerializer(approval.complaint).data,
        })


class ComplaintStartActionAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, complaint_id, *args, **kwargs):
        complaint = visible_complaints_for_user(request.user, Complaint.objects.all()).filter(
            complaint_id=complaint_id,
        ).first()
        if not complaint:
            return Response({'error': 'Complaint not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            complaint = start_action_execution(complaint, request.user)
        except PermissionError as exc:
            raise PermissionDenied(str(exc)) from exc
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ComplaintSerializer(complaint).data)


class ComplaintFinalUpdateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, complaint_id, *args, **kwargs):
        complaint = visible_complaints_for_user(request.user, Complaint.objects.all()).filter(
            complaint_id=complaint_id,
        ).first()
        if not complaint:
            return Response({'error': 'Complaint not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = FinalComplaintUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            complaint = close_complaint_after_execution(
                complaint,
                request.user,
                serializer.validated_data['cad_date'],
                serializer.validated_data.get('production_updates_container', ''),
            )
        except PermissionError as exc:
            raise PermissionDenied(str(exc)) from exc
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ComplaintSerializer(complaint).data)


class NotificationListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        notifications = Notification.objects.filter(recipient=request.user).select_related('complaint')[:100]
        return Response(NotificationSerializer(notifications, many=True).data)


class NotificationReadAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, notification_id, *args, **kwargs):
        notification = Notification.objects.filter(pk=notification_id, recipient=request.user).first()
        if not notification:
            return Response({'error': 'Notification not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=['is_read'])
        return Response(NotificationSerializer(notification).data)

class SKUListCreateAPIView(ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsCatalogAdminOrReadOnly]
    serializer_class = SKUSerializer
    queryset = SKU.objects.select_related('region').all().order_by('code')

class SKURetrieveUpdateDestroyAPIView(RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated, IsCatalogAdminOrReadOnly]
    serializer_class = SKUSerializer
    queryset = SKU.objects.all()

class VehicleListCreateAPIView(ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsCatalogAdminOrReadOnly]
    serializer_class = YearRangeSerializer
    queryset = YearRange.objects.all().order_by('-id')

class VehicleRetrieveUpdateDestroyAPIView(RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated, IsCatalogAdminOrReadOnly]
    serializer_class = YearRangeSerializer
    queryset = YearRange.objects.all()
