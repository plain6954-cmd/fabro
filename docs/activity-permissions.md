# FABRO activity authorization inventory

The registry in management/services/activity_permissions.py is authoritative. The route inventory in management/services/activity_routes.py is used by both authenticated HTML middleware and the DRF post-authentication adapter. All registered application routes have an inventory/essential classification regression assertion.

97 supported activity keys across 18 categories. No permissions are created for viewer mechanics.

## Category counts

| Category | Keys |
|---|---:|
| Dashboard & Navigation | 1 |
| Vehicle Catalog | 6 |
| Pattern Master | 8 |
| Measurements | 7 |
| Reference Images | 7 |
| Designer Uploads | 10 |
| Design Folders | 5 |
| Design Approval | 6 |
| Colors & Color Approval | 8 |
| SKU Management | 4 |
| Complaints | 8 |
| Complaint Workflow | 7 |
| Master Settings | 4 |
| Notifications | 2 |
| Internal Chat | 2 |
| Reports & Activity | 2 |
| ERP Administration | 4 |
| User & Access Management | 6 |

## Access rules and compatibility

- Effective access requires an enabled activity plus the existing view/service/object authorization. Grants do not confer stage assignment, country scope, reviewer identity, ownership, or a valid workflow transition.
- Empty UserProfile.activity_permissions inherits compatibility defaults. Migration 0050 adds that empty JSON field and UserAccessAudit; it does not rewrite groups, roles, reviewer assignments, passwords or existing review records.
- Existing roles are Country Executive, Factory Viewer, Factory Executive, Factory Complaint Registrar, 3D Designer Freelancer, Approver and Admin. PM/OM/CAD/ED/MD remain approval-role metadata. Staff flags and existing Django file-management permissions are respected.
- Role-default configuration may override eligible defaults using ACTIVITY_ROLE_DEFAULTS, keyed by workflow role or PM/OM/CAD/ED/MD for Approver. This is configuration, not a new role system. No cross-request permission cache is used.
- Missing key = inherit. Stored values are allow or deny. The panel checks effective selections, marks individual differences, and normalizes equivalent selections back to inherit. Staff/group eligibility changes preserve individual overrides; explicit role switches and Reset replace selections after confirmation. Dependencies are checked by the server.
- Active superusers and explicit Admin profiles retain mandatory administrative access, including catalog management. MD retains established ERP visibility, but cannot assign roles, manage overrides, create authority-bearing accounts, or reset/reactivate/delete Admin accounts. Existing superuser-only account protections remain.
- Own scopes require an actual uploader/creator FK matching the user. Unknown ownership is never treated as own. All scopes still require existing record visibility and business authorization. Shared references are not treated as vehicle ownership merely because a user uploaded them.
- Recorded design review cycles, reviewed/approved/rejected design metadata and historical approved/rejected designer files block deletion regardless of permission. Folder, vehicle, bulk alteration and Django catalog ancestor deletion use the same guard; transaction locks coordinate with review submission. Deleting a user cannot cascade away their design review history; deactivate instead.
- Measurements have uploader records but no persisted submission/review lifecycle. Their existing eligible-file/ownership rules apply; this feature does not fabricate a measurement approval workflow.
- Catalog lookups consumed by authorized complaint forms remain available independently of master-setting administration. Existing object-level country and complaint-type restrictions remain authoritative.
- Authenticated file proxies replace raw reference/design/measurement/swatch URLs. Comparison and measurement streaming share the existing byte-range behavior. Local development private media paths are also gated. External storage must retain its existing private-bucket configuration; changing a stored URL already issued by object storage is outside application request authorization.
- Login/logout, own profile/password/language, push subscription security and the own access-state endpoint are essentials, not toggles. Access-change notifications link to the authenticated profile even if notification features are denied.
- New audit records retain actor, target FK and username, old/new role identity, exact override/group changes, active flag and timestamp; no passwords/hashes are recorded. Existing Django administration continues to have its native audit log.

## Complete action inventory

| Permission key | Category / UI entry point | Backend views / endpoints | Existing restrictions | Ownership | Supported |
|---|---|---|---|---|---|
| `dashboard.view` | Dashboard & Navigation / System Dashboard | index, api_dashboard | authenticated; existing record/state checks | existing object authorization | Yes |
| `vehicle.view` | Vehicle Catalog / Vehicle catalog / REST catalog | get_models, get_sub_models, get_year_ranges, get_available_years, admin_brand_tree, api_vehicles_list_create, api_vehicle_detail | authenticated; existing record/state checks | existing object authorization | Yes |
| `vehicle.create` | Vehicle Catalog / Vehicle catalog / REST catalog | car_details, api_vehicles_list_create | catalog; existing record/state checks | existing object authorization | Yes |
| `vehicle.edit` | Vehicle Catalog / Vehicle catalog / REST catalog | api_vehicle_detail | catalog; existing record/state checks | existing object authorization | Yes |
| `vehicle.delete` | Vehicle Catalog / Vehicle catalog / REST catalog | api_vehicle_detail DELETE, Django catalog admin delete/bulk-delete | catalog; existing record/state checks | existing object authorization | Yes |
| `vehicle.import` | Vehicle Catalog / Vehicle catalog / REST catalog | upload_car_csv | catalog; existing record/state checks | existing object authorization | Yes |
| `vehicle.photo` | Vehicle Catalog / Vehicle catalog / REST catalog | upload_vehicle_photo | superuser; existing record/state checks | existing object authorization | Yes |
| `pattern.view` | Pattern Master / Pattern Master / row actions | car_details, pattern_vehicle_list_api, pattern_vehicle_count_api, get_next_pattern_serial_api | authenticated; existing record/state checks | existing object authorization | Yes |
| `pattern.edit` | Pattern Master / Pattern Master / row actions | edit_car_detail, update_fitting_confirmation_api, update_vehicle_country_api, update_drive_api, update_measurement_country_api | catalog; existing record/state checks | existing object authorization | Yes |
| `pattern.delete` | Pattern Master / Pattern Master / row actions | delete_car_detail, bulk_delete_patterns_api | catalog; existing record/state checks | existing object authorization | Yes |
| `pattern.alter` | Pattern Master / Pattern Master / row actions | bulk_delete_patterns_api | catalog; existing record/state checks | existing object authorization | Yes |
| `pattern.decide` | Pattern Master / Pattern Master / row actions | decide_pattern_alteration_api | pattern_review; existing record/state checks | existing object authorization | Yes |
| `pattern.drive_view` | Pattern Master / Pattern Master / row actions | vehicle_drive_links_api | authenticated; existing record/state checks | existing object authorization | Yes |
| `pattern.drive_add` | Pattern Master / Pattern Master / row actions | vehicle_drive_links_api, update_vehicle_google_drive_api | drive; existing record/state checks | existing object authorization | Yes |
| `pattern.drive_delete` | Pattern Master / Pattern Master / row actions | delete_vehicle_drive_link_api | superuser; existing record/state checks | existing object authorization | Yes |
| `reference.view_own` | Reference Images / Reference gallery / comparison | get_design_folders_api, get_design_folder_detail_api, design_comparison_manifest, design_comparison_file, pattern_design_image_download, delete_design_image_api | authenticated; existing record/state checks | uploader/creator | Yes |
| `reference.view_all` | Reference Images / Reference gallery / comparison | get_design_folders_api, get_design_folder_detail_api, design_comparison_manifest, design_comparison_file, pattern_design_image_download, delete_design_image_api | authenticated; existing record/state checks | uploader/creator | Yes |
| `reference.upload` | Reference Images / Reference gallery / comparison | get_design_folders_api, get_design_folder_detail_api, design_comparison_manifest, design_comparison_file, pattern_design_image_download, delete_design_image_api | reference_upload; existing record/state checks | existing object authorization | Yes |
| `reference.download_own` | Reference Images / Reference gallery / comparison | get_design_folders_api, get_design_folder_detail_api, design_comparison_manifest, design_comparison_file, pattern_design_image_download, delete_design_image_api | authenticated; existing record/state checks | uploader/creator | Yes |
| `reference.download_all` | Reference Images / Reference gallery / comparison | get_design_folders_api, get_design_folder_detail_api, design_comparison_manifest, design_comparison_file, pattern_design_image_download, delete_design_image_api | authenticated; existing record/state checks | uploader/creator | Yes |
| `reference.delete_own` | Reference Images / Reference gallery / comparison | get_design_folders_api, get_design_folder_detail_api, design_comparison_manifest, design_comparison_file, pattern_design_image_download, delete_design_image_api | file_delete; existing record/state checks | uploader/creator | Yes |
| `reference.delete_all` | Reference Images / Reference gallery / comparison | get_design_folders_api, get_design_folder_detail_api, design_comparison_manifest, design_comparison_file, pattern_design_image_download, delete_design_image_api | file_delete; existing record/state checks | uploader/creator | Yes |
| `design.view_own` | Designer Uploads / 3D Design gallery / comparison | get_design_folders_api, get_design_folder_detail_api, design_comparison_manifest, design_comparison_file, pattern_design_image_download, design_approval_detail, delete_design_image_api | authenticated; existing record/state checks | uploader/creator | Yes |
| `design.view_all` | Designer Uploads / 3D Design gallery / comparison | get_design_folders_api, get_design_folder_detail_api, design_comparison_manifest, design_comparison_file, pattern_design_image_download, design_approval_detail, delete_design_image_api | authenticated; existing record/state checks | uploader/creator | Yes |
| `design.upload` | Designer Uploads / 3D Design gallery / comparison | get_design_folders_api, get_design_folder_detail_api, design_comparison_manifest, design_comparison_file, pattern_design_image_download, design_approval_detail, delete_design_image_api | design_upload; existing record/state checks | existing object authorization | Yes |
| `design.download_own` | Designer Uploads / 3D Design gallery / comparison | get_design_folders_api, get_design_folder_detail_api, design_comparison_manifest, design_comparison_file, pattern_design_image_download, design_approval_detail, delete_design_image_api | authenticated; existing record/state checks | uploader/creator | Yes |
| `design.download_all` | Designer Uploads / 3D Design gallery / comparison | get_design_folders_api, get_design_folder_detail_api, design_comparison_manifest, design_comparison_file, pattern_design_image_download, design_approval_detail, delete_design_image_api | authenticated; existing record/state checks | uploader/creator | Yes |
| `design.delete_own` | Designer Uploads / 3D Design gallery / comparison | get_design_folders_api, get_design_folder_detail_api, design_comparison_manifest, design_comparison_file, pattern_design_image_download, design_approval_detail, delete_design_image_api | design_delete_own; existing record/state checks | uploader/creator | Yes |
| `design.delete_all` | Designer Uploads / 3D Design gallery / comparison | get_design_folders_api, get_design_folder_detail_api, design_comparison_manifest, design_comparison_file, pattern_design_image_download, design_approval_detail, delete_design_image_api | file_delete; existing record/state checks | uploader/creator | Yes |
| `measurement.view_own` | Measurements / Pattern Master Measurements tab | get_measurement_files_api, measurement_file_download, delete_measurement_file_api | authenticated; existing record/state checks | uploader/creator | Yes |
| `measurement.view_all` | Measurements / Pattern Master Measurements tab | get_measurement_files_api, measurement_file_download, delete_measurement_file_api | authenticated; existing record/state checks | uploader/creator | Yes |
| `measurement.upload` | Measurements / Pattern Master Measurements tab | upload_measurement_files_api | authenticated; existing record/state checks | existing object authorization | Yes |
| `measurement.download_own` | Measurements / Pattern Master Measurements tab | get_measurement_files_api, measurement_file_download, delete_measurement_file_api | authenticated; existing record/state checks | uploader/creator | Yes |
| `measurement.download_all` | Measurements / Pattern Master Measurements tab | get_measurement_files_api, measurement_file_download, delete_measurement_file_api | authenticated; existing record/state checks | uploader/creator | Yes |
| `measurement.delete_own` | Measurements / Pattern Master Measurements tab | get_measurement_files_api, measurement_file_download, delete_measurement_file_api | authenticated; existing record/state checks | uploader/creator | Yes |
| `measurement.delete_all` | Measurements / Pattern Master Measurements tab | get_measurement_files_api, measurement_file_download, delete_measurement_file_api | catalog; existing record/state checks | uploader/creator | Yes |
| `design.resubmit_own` | Designer Uploads / 3D Design gallery / comparison | resubmit_design_image_api, design_approval_detail POST resubmit | design_upload; existing record/state checks | uploader/creator | Yes |
| `design.resubmit_all` | Designer Uploads / 3D Design gallery / comparison | resubmit_design_image_api, design_approval_detail POST resubmit | superuser; existing record/state checks | uploader/creator | Yes |
| `design.history` | Designer Uploads / 3D Design gallery / comparison | design_comparison_manifest, get_design_folders_api, design_approval_detail, design_review_voice_audio | design_view; existing record/state checks | existing object authorization | Yes |
| `folder.view` | Design Folders / Design folder gallery | get_design_folders_api, get_design_folder_detail_api, delete_design_folder_api | authenticated; existing record/state checks | existing object authorization | Yes |
| `folder.create` | Design Folders / Design folder gallery | create_design_folder_api | assets; existing record/state checks | existing object authorization | Yes |
| `folder.rename` | Design Folders / Design folder gallery | rename_design_folder_api | assets; existing record/state checks | existing object authorization | Yes |
| `folder.delete_own` | Design Folders / Design folder gallery | delete_design_folder_api | file_delete; existing record/state checks | uploader/creator | Yes |
| `folder.delete_all` | Design Folders / Design folder gallery | delete_design_folder_api | file_delete; existing record/state checks | uploader/creator | Yes |
| `design_approval.view` | Design Approval / Approvals Workspace / Design Review / comparison approval column | design_approval_detail, design_approvals_list | design_view; existing record/state checks | existing object authorization | Yes |
| `design_approval.history` | Design Approval / Approvals Workspace / Design Review / comparison approval column | design_review_voice_audio, design_comparison_manifest, get_design_folders_api, design_approval_detail | design_view; existing record/state checks | existing object authorization | Yes |
| `design_approval.comment` | Design Approval / Approvals Workspace / Design Review / comparison approval column | approve_design_image_api, reject_design_image_api, design_approval_detail, design_review_voice_audio | review; existing record/state checks | existing object authorization | Yes |
| `design_approval.voice` | Design Approval / Approvals Workspace / Design Review / comparison approval column | approve_design_image_api, reject_design_image_api, design_approval_detail, design_review_voice_audio | review; existing record/state checks | existing object authorization | Yes |
| `design_approval.approve` | Design Approval / Approvals Workspace / Design Review / comparison approval column | approve_design_image_api | review; existing record/state checks | existing object authorization | Yes |
| `design_approval.reject` | Design Approval / Approvals Workspace / Design Review / comparison approval column | reject_design_image_api | review; existing record/state checks | existing object authorization | Yes |
| `color.view` | Colors & Color Approval / Pattern Master colors / color approval drawer | master_colors_api, get_color_selection_details_api, color_selection_file, submit_color_decision_api | authenticated; existing record/state checks | existing object authorization | Yes |
| `color.create` | Colors & Color Approval / Pattern Master colors / color approval drawer | create_color_api | catalog; existing record/state checks | existing object authorization | Yes |
| `color.edit` | Colors & Color Approval / Pattern Master colors / color approval drawer | update_color_api | catalog; existing record/state checks | existing object authorization | Yes |
| `color.delete` | Colors & Color Approval / Pattern Master colors / color approval drawer | delete_color_api | catalog; existing record/state checks | existing object authorization | Yes |
| `color.submit` | Colors & Color Approval / Pattern Master colors / color approval drawer | save_color_selection_api | authenticated; existing record/state checks | existing object authorization | Yes |
| `color.history` | Colors & Color Approval / Pattern Master colors / color approval drawer | get_color_selection_details_api, submit_color_decision_api, approvals_list stage=colors | authenticated; existing record/state checks | existing object authorization | Yes |
| `color.approve` | Colors & Color Approval / Pattern Master colors / color approval drawer | get_color_selection_details_api, submit_color_decision_api, approvals_list stage=colors | color_review; existing record/state checks | existing object authorization | Yes |
| `color.reject` | Colors & Color Approval / Pattern Master colors / color approval drawer | get_color_selection_details_api, submit_color_decision_api, approvals_list stage=colors | color_review; existing record/state checks | existing object authorization | Yes |
| `sku.view` | SKU Management / SKU page / REST catalog | get_filtered_skus, add_sku, api_skus_list_create, api_sku_detail | authenticated; existing record/state checks | existing object authorization | Yes |
| `sku.create` | SKU Management / SKU page / REST catalog | add_sku, api_skus_list_create | catalog; existing record/state checks | existing object authorization | Yes |
| `sku.edit` | SKU Management / SKU page / REST catalog | edit_sku, api_sku_detail | catalog; existing record/state checks | existing object authorization | Yes |
| `sku.delete` | SKU Management / SKU page / REST catalog | delete_sku | catalog; existing record/state checks | existing object authorization | Yes |
| `complaint.view` | Complaints / Complaint list / registration / details | get_complaint_type_options, get_material_variants, complaint_list, edit_complaint, execute_complaint, api_complaints_list_create, api_complaint_detail | authenticated; existing record/state checks | existing object authorization | Yes |
| `complaint.create` | Complaints / Complaint list / registration / details | add_complaint, api_complaints_list_create | complaint_create; existing record/state checks | existing object authorization | Yes |
| `complaint.edit` | Complaints / Complaint list / registration / details | edit_complaint, api_complaint_detail | report_edit; existing record/state checks | existing object authorization | Yes |
| `complaint.delete` | Complaints / Complaint list / registration / details | delete_complaint | erp; existing record/state checks | existing object authorization | Yes |
| `complaint.export` | Complaints / Complaint list / registration / details | export_complaints | authenticated; existing record/state checks | existing object authorization | Yes |
| `complaint.media_view` | Complaints / Complaint list / registration / details | complaint_media_download | authenticated; existing record/state checks | existing object authorization | Yes |
| `complaint.media_upload` | Complaints / Complaint list / registration / details | complaint_media_signed_upload | authenticated; existing record/state checks | existing object authorization | Yes |
| `complaint.media_delete` | Complaints / Complaint list / registration / details | complaint_media_discard_uploads | authenticated; existing record/state checks | existing object authorization | Yes |
| `workflow.view` | Complaint Workflow / Factory Review / approval inbox / execution forms | approvals_list, approval_inbox, approval_review, quick_approval_decision_api, api_approval_inbox, api_approval_decision | approvals_view; existing record/state checks | existing object authorization | Yes |
| `workflow.factory_review` | Complaint Workflow / Factory Review / approval inbox / execution forms | factory_review_complaint, api_factory_review | factory; existing record/state checks | existing object authorization | Yes |
| `workflow.approve` | Complaint Workflow / Factory Review / approval inbox / execution forms | approval_review, quick_approval_decision_api, api_approval_decision, execute_complaint | complaint_review; existing record/state checks | existing object authorization | Yes |
| `workflow.reject` | Complaint Workflow / Factory Review / approval inbox / execution forms | approval_review, quick_approval_decision_api, api_approval_decision, execute_complaint | complaint_review; existing record/state checks | existing object authorization | Yes |
| `workflow.start` | Complaint Workflow / Factory Review / approval inbox / execution forms | api_start_action | factory; existing record/state checks | existing object authorization | Yes |
| `workflow.verify_submit` | Complaint Workflow / Factory Review / approval inbox / execution forms | api_submit_execution_verification | factory; existing record/state checks | existing object authorization | Yes |
| `workflow.close` | Complaint Workflow / Factory Review / approval inbox / execution forms | api_final_update | factory; existing record/state checks | existing object authorization | Yes |
| `master.view` | Master Settings / ERP Master Settings | master_settings | erp; existing record/state checks | existing object authorization | Yes |
| `master.create` | Master Settings / ERP Master Settings | master_settings | erp; existing record/state checks | existing object authorization | Yes |
| `master.edit` | Master Settings / ERP Master Settings | edit_master_setting | erp; existing record/state checks | existing object authorization | Yes |
| `master.delete` | Master Settings / ERP Master Settings | delete_master_setting | erp; existing record/state checks | existing object authorization | Yes |
| `notification.view` | Notifications / Notifications list / badge links | notification_list, api_notifications | authenticated; existing record/state checks | existing object authorization | Yes |
| `notification.read` | Notifications / Notifications list / badge links | open_notification, mark_all_notifications_read, api_notification_read | authenticated; existing record/state checks | existing object authorization | Yes |
| `chat.view` | Internal Chat / Internal Chat | chat_view, chat_users_api, chat_messages_api | authenticated; existing record/state checks | existing object authorization | Yes |
| `chat.send` | Internal Chat / Internal Chat | chat_send_api | authenticated; existing record/state checks | existing object authorization | Yes |
| `reports.pattern_history` | Reports & Activity / Pattern history / ERP Activity Logs | pattern_logs_api | authenticated; existing record/state checks | existing object authorization | Yes |
| `reports.activity` | Reports & Activity / Pattern history / ERP Activity Logs | admin_panel section=logs / Django audit admin | erp; existing record/state checks | existing object authorization | Yes |
| `erp.view` | ERP Administration / ERP sidebar / Control Tower / sessions | admin_panel, admin_panel_alias | erp; existing record/state checks | existing object authorization | Yes |
| `erp.control_tower` | ERP Administration / ERP sidebar / Control Tower / sessions | admin_control_tower | erp; existing record/state checks | existing object authorization | Yes |
| `erp.sessions_view` | ERP Administration / ERP sidebar / Control Tower / sessions | admin_panel section=sessions/dashboard | erp; existing record/state checks | existing object authorization | Yes |
| `erp.sessions_terminate` | ERP Administration / ERP sidebar / Control Tower / sessions | terminate_session, terminate_all_sessions | erp; existing record/state checks | existing object authorization | Yes |
| `users.create` | User & Access Management / ERP Users / User Control Panel / Django groups | user_control_data, user_control_save, edit_user, admin_panel / Django admin | admin; existing record/state checks | existing object authorization | Yes |
| `users.manage` | User & Access Management / ERP Users / User Control Panel / Django groups | edit_user, user_control_data, user_control_save, delete_user | erp; existing record/state checks | existing object authorization | Yes |
| `users.permissions` | User & Access Management / ERP Users / User Control Panel / Django groups | user_control_data, user_control_save, edit_user, admin_panel / Django admin | admin; existing record/state checks | existing object authorization | Yes |
| `users.groups` | User & Access Management / ERP Users / User Control Panel / Django groups | user_control_data, user_control_save, edit_user, admin_panel / Django admin | admin; existing record/state checks | existing object authorization | Yes |
| `users.password` | User & Access Management / ERP Users / User Control Panel / Django groups | edit_user POST reset_password, user_control_save | erp; existing record/state checks | existing object authorization | Yes |
| `users.photo_delete` | User & Access Management / ERP Users / User Control Panel / Django groups | delete_user_photo | erp; existing record/state checks | existing object authorization | Yes |

## Notification impact: Updated

Event: a saved role, account activation state, group-derived access or individual override change. Recipient: the affected existing account only, calculated server-side. In-app: existing Notification model, access_change type. Web Push: existing notify_user/send_push_on_commit architecture with privacy-safe text. Destination: /profile/. Trigger: transaction.on_commit after a successful atomic save; validation rollback and no-op access saves do not notify. Push failure does not break account changes. Existing complaint/design notification recipient rules are unchanged; notifications never bypass destination authorization.

## Deployment

NOT DEPLOYED. Apply migration 0050 and the normal static-asset collection when an authorized deployment is performed. No new dependencies or infrastructure.
