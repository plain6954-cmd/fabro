"""Rehearse additive roles initialization and immediate rollback on local PostgreSQL."""
from unittest import skipUnless
from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class RolesMigrationTests(TransactionTestCase):
    @skipUnless(connection.vendor=='postgresql','Historical-schema rehearsal uses the verified local PostgreSQL test database')
    def test_existing_profiles_permissions_groups_and_reviews_survive_round_trip(self):
        self.assertIn(connection.settings_dict['HOST'],('127.0.0.1','localhost'))
        self.assertTrue(connection.settings_dict['NAME'].startswith('test_'))
        previous=('management','0054_patterndesignimage_deleted_at_and_more')
        current=('management','0056_initialize_activity_roles')
        executor=MigrationExecutor(connection);leaves=executor.loader.graph.leaf_nodes()
        executor.migrate([previous])
        try:
            old=executor.loader.project_state([previous]).apps
            User=old.get_model('auth','User');Profile=old.get_model('management','UserProfile')
            Group=old.get_model('auth','Group');Permission=old.get_model('auth','Permission')
            users=[];profiles=[]
            for index,(role,stage,staff,su) in enumerate((('country_executive','',False,False),('approver','CAD',False,False),('factory_viewer','',True,False),('admin','',True,True))):
                user=User.objects.create(username=f'roles-migration-{index}',is_staff=staff,is_superuser=su,password='!')
                p=Profile.objects.create(user_id=user.pk,role=role,approval_role=stage,department='Retained department',
                    phone_number='12345',photo='profile_photos/retained.png',activity_permissions={'chat.send':'deny'})
                users.append(user);profiles.append(p)
            group=Group.objects.create(name='Retained file ownership permissions')
            permission=Permission.objects.get(codename='delete_patterndesignimage',content_type__app_label='management')
            group.permissions.add(permission);users[2].groups.add(group)
            user_values=list(User.objects.filter(pk__in=[user.pk for user in users]).values())
            profile_values={p.pk:Profile.objects.filter(pk=p.pk).values().get() for p in profiles}
            image=old.get_model('management','PatternDesignImage').objects.create(
                uploaded_by_id=users[0].pk,image='retained/design.png',title='Retained revision')
            review=old.get_model('management','PatternDesignApproval').objects.create(
                design_image_id=image.pk,designer_id=users[0].pk,cycle=2,
                cad_reviewer_id=users[1].pk,cad_status='rejected',cad_comment='Retained review',cad_change_type='major')
            history={name:list(old.get_model('management',name).objects.values())
                for name in ('PatternDesignImage','PatternDesignApproval')}
            executor=MigrationExecutor(connection);executor.migrate([current])
            new=executor.loader.project_state([current]).apps;NewProfile=new.get_model('management','UserProfile')
            self.assertEqual(list(new.get_model('auth','User').objects.filter(pk__in=[u.pk for u in users]).values()),user_values)
            for p in profiles:
                after=NewProfile.objects.get(pk=p.pk);before=profile_values[p.pk]
                self.assertIsNotNone(after.activity_role_id)
                for key,value in before.items():
                    if key!='activity_permissions':self.assertEqual(getattr(after,key),value)
                for key,value in before['activity_permissions'].items():self.assertEqual(after.activity_permissions[key],value)
            self.assertTrue(new.get_model('auth','User').objects.get(pk=users[2].pk).groups.filter(pk=group.pk).exists())
            self.assertEqual(new.get_model('management','ActivityRole').objects.count(),11)
            for name,values in history.items():
                self.assertEqual(list(new.get_model('management',name).objects.values()),values)
            # Idempotent initialization never duplicates roles or rewrites existing selections.
            from importlib import import_module
            import_module('management.migrations.0056_initialize_activity_roles').seed(new,connection.schema_editor())
            self.assertEqual(new.get_model('management','ActivityRole').objects.count(),11)
            executor=MigrationExecutor(connection);executor.migrate([previous])
            restored=executor.loader.project_state([previous]).apps
            for pk,before in profile_values.items():
                self.assertEqual(restored.get_model('management','UserProfile').objects.filter(pk=pk).values().get(),before)
        finally:
            MigrationExecutor(connection).migrate(leaves)
