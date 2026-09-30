import pytest
import time
from app import db
from app.infrastructure.database.models import User, Role, Organization, Project
from app.infrastructure.database.models.models import (
    ProjectMember,
    FacilitatorNote,
    Stage8StandardizationKnowledgeSharingProjectClosure,
    AnalyticsUsage
)


def test_delete_user_with_dependent_relations(client, app, auth_context):
    """
    Verify deleting a user (e.g. CEO or team member) who has:
      1. Stage 8 final approvals (foreign key on stage_8_..._final_approval_by)
      2. Project memberships (non-nullable foreign key)
      3. Facilitator notes (non-nullable created_by)
      4. Analytics usage entries (non-nullable user_id)
    succeeds cleanly without foreign key constraint violations.
    """
    with app.app_context():
        headers = auth_context['headers']
        org_id = auth_context['org_id']

        ts = int(time.time() * 1000)
        ceo_role = Role.query.filter_by(name='CEO').first()
        if not ceo_role:
            ceo_role = Role(name='CEO', description='Chief Executive Officer')
            db.session.add(ceo_role)
            db.session.commit()

        # Create target user
        test_ceo = User(
            email=f"test_ceo_{ts}@test.org",
            username=f"test_ceo_{ts}",
            full_name="Test CEO",
            org_id=org_id,
            role_id=ceo_role.id,
            is_active=True,
            status="Active"
        )
        test_ceo.set_password("SecurePass123!")
        db.session.add(test_ceo)
        db.session.commit()
        target_uid = test_ceo.id

        # Create test project
        short_uid = f"PRJ-T{int(time.time()) % 1000000:06d}"
        project = Project(
            project_uid=short_uid,
            title=f"Test Project User Delete {ts}",
            description="Project to test user deletion dependencies",
            org_id=org_id,
            creator_id=target_uid,
            status="Active"
        )
        db.session.add(project)
        db.session.commit()

        # Add project member
        pm = ProjectMember(
            project_id=project.id,
            user_id=target_uid
        )
        db.session.add(pm)

        # Add Stage 8 closure with final_approval_by = target_uid
        stage8 = Stage8StandardizationKnowledgeSharingProjectClosure(
            org_id=org_id,
            project_id=project.id,
            final_approval_by=target_uid,
            status="Completed"
        )
        db.session.add(stage8)

        # Add Facilitator Note
        fn = FacilitatorNote(
            org_id=org_id,
            project_id=project.id,
            stage_number=1,
            created_by=target_uid,
            note_text="Test note for user deletion"
        )
        db.session.add(fn)

        # Add AnalyticsUsage
        au = AnalyticsUsage(
            org_id=org_id,
            user_id=target_uid,
            module_name="Analytics",
            feature_name="dashboard",
            action_type="login"
        )
        db.session.add(au)
        db.session.commit()

        stage8_id = stage8.id
        proj_id = project.id

        # Execute DELETE via API: /api/admin/users/<target_uid>
        res = client.delete(f'/api/admin/users/{target_uid}', headers=headers)
        assert res.status_code == 200, f"Delete failed: {res.get_json()}"
        data = res.get_json()
        assert 'permanently deleted' in data.get('message', '').lower()

        # Verify user is deleted
        deleted_user = db.session.get(User, target_uid)
        assert deleted_user is None

        # Verify Stage 8 final_approval_by was nullified
        stage8_refetched = db.session.get(Stage8StandardizationKnowledgeSharingProjectClosure, stage8_id)
        assert stage8_refetched is not None
        assert stage8_refetched.final_approval_by is None

        # Verify project creator_id was nullified
        project_refetched = db.session.get(Project, proj_id)
        assert project_refetched is not None
        assert project_refetched.creator_id is None

        # Clean up project
        db.session.delete(stage8_refetched)
        db.session.delete(project_refetched)
        db.session.commit()
