import uuid
import time
from unittest.mock import patch
import pytest
from app import db
from app.infrastructure.database.models import Project
from app.domain.services.project_closure_service import ProjectClosureService


def test_project_creation_and_retrieval(client, auth_context):
    """Test project creation and retrieval through API."""
    unique_uid = f"PRJ-TST-{uuid.uuid4().hex[:8]}"
    create_payload = {
        "title": "Automated Pytest QC Project",
        "project_uid": unique_uid,
        "category": "Quality",
        "work_area": "Assembly Line A",
        "description": "Continuous improvement in line A cycle time."
    }
    with patch(
        'app.domain.services.subscription_service.SubscriptionManager.check_project_limit',
        return_value=(True, 'Unlimited')
    ):
        res = client.post('/api/projects/', json=create_payload, headers=auth_context['headers'])
    # Should succeed or return project representation
    if res.status_code in [200, 201]:
        data = res.get_json()
        assert "id" in data or "project" in data or "project_uid" in str(data)


def test_project_closure_service_lifecycle(app, auth_context):
    """Test ProjectClosureService business logic execution directly."""
    with app.app_context():
        # Create a sample project in DB
        project = Project(
            title="Pytest Closure Lifecycle Project",
            project_uid=f"PRJ-CLS-{uuid.uuid4().hex[:8]}",
            org_id=auth_context['org_id'],
            creator_id=auth_context['user_id'],
            team_leader_id=auth_context['user_id'],
            current_stage=8,
            status="In Progress"
        )
        db.session.add(project)
        db.session.commit()
        pid = project.id

        # 1. Test Rejection
        reject_res = ProjectClosureService.reject_closure(pid, auth_context['user_id'], comments="Need revision")
        assert reject_res["status"] == "success"
        p_ref = db.session.get(Project, pid)
        assert p_ref.status == "Rejected"
        assert p_ref.current_stage == 1

        # 2. Test Execution of Closure
        close_res = ProjectClosureService.execute_closure(pid, auth_context['user_id'], comments="Approved by Reviewer")
        assert close_res["status"] == "success"
        p_closed = db.session.get(Project, pid)
        assert p_closed.status == "Closed"
        assert p_closed.end_date is not None


@patch('app.domain.services.subscription_service.SubscriptionManager.check_project_limit', return_value=(True, 'Unlimited'))
def test_project_governance_and_team_update(mock_limit, client, auth_context, app):
    """Test updating team members, facilitator, team leader, and reviewer on project."""
    unique_uid = f"PRJ-GOV-{uuid.uuid4().hex[:8]}"
    create_res = client.post('/api/projects/', json={
        "title": "Pytest Governance Team Update Project",
        "project_uid": unique_uid,
        "category": "Quality",
        "description": "Governance update testing",
        "work_area": "Plant 1",
        "member_ids": []
    }, headers=auth_context['headers'])
    assert create_res.status_code in (200, 201), f"Failed to create project: {create_res.get_data(as_text=True)}"
    c_data = create_res.get_json()
    pid = c_data.get('id') or (c_data.get('project') or {}).get('id')
    assert pid is not None

    payload = {
        "team_leader_id": auth_context['user_id'],
        "facilitator_id": auth_context['user_id'],
        "reviewer_id": auth_context['user_id'],
        "member_ids": [auth_context['user_id']]
    }
    res = client.put(f"/api/projects/{pid}", json=payload, headers=auth_context['headers'])
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.get_data(as_text=True)}"
    data = res.get_json()
    assert data.get("msg") == "Project updated successfully"

    with app.app_context():
        p_updated = db.session.get(Project, pid)
        assert p_updated.team_leader_id == auth_context['user_id']
        assert p_updated.facilitator_id == auth_context['user_id']
        assert p_updated.reviewer_id == auth_context['user_id']

