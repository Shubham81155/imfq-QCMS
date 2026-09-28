import pytest
import json
import uuid
from datetime import datetime, timedelta, timezone
from app import db
from app.infrastructure.database.models.models import User, Organization, Role, PlatformSettings


def test_settings_dashboard(client, super_admin_context):
    res = client.get('/api/super-admin/settings/dashboard', headers=super_admin_context['headers'])
    assert res.status_code == 200
    data = res.get_json()
    assert data['status'] == 'success'
    assert 'kpis' in data['data']
    assert 'ai_insights' in data['data']
    assert data['data']['kpis']['platform_version'] == '1.0.0'


def test_get_settings(client, super_admin_context):
    res = client.get('/api/super-admin/settings', headers=super_admin_context['headers'])
    assert res.status_code == 200
    data = res.get_json()
    assert data['status'] == 'success'
    assert 'site_name' in data['data']


def test_update_settings(client, super_admin_context):
    payload = {
        "site_name": "Updated QCMS Site Name",
        "trial_period_days": 30,
        "security_settings": {
            "password_min_length": 12,
            "password_uppercase": True
        }
    }
    res = client.put('/api/super-admin/settings', headers=super_admin_context['headers'], json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data['status'] == 'success'

    # Read back settings
    res = client.get('/api/super-admin/settings', headers=super_admin_context['headers'])
    data = res.get_json()
    assert data['data']['site_name'] == "Updated QCMS Site Name"
    assert data['data']['trial_period_days'] == 30
    assert data['data']['security_settings']['password_min_length'] == 12
    assert data['data']['security_settings']['password_uppercase'] is True


def test_email_config_validation(client, super_admin_context):
    res = client.post('/api/super-admin/settings/test-email', headers=super_admin_context['headers'], json={
        "to_email": "test@test.com"
    })
    # Since SMTP is not configured, it should return 400
    assert res.status_code == 400


def test_api_keys_management(client, super_admin_context):
    # 1. Create a key
    res = client.post('/api/super-admin/settings/api-keys', headers=super_admin_context['headers'], json={
        "label": "Test Key Pytest",
        "scopes": ["read", "write"]
    })
    assert res.status_code == 201
    data = res.get_json()
    assert 'secret' in data['data']
    key_id = data['data']['id']

    # 2. List keys
    res = client.get('/api/super-admin/settings/api-keys', headers=super_admin_context['headers'])
    assert res.status_code == 200
    data = res.get_json()
    assert any(k['id'] == key_id for k in data['data'])

    # 3. Revoke key
    res = client.delete(f'/api/super-admin/settings/api-keys/{key_id}', headers=super_admin_context['headers'])
    assert res.status_code == 200

    # 4. List keys again (should not include revoked key)
    res = client.get('/api/super-admin/settings/api-keys', headers=super_admin_context['headers'])
    data = res.get_json()
    assert not any(k['id'] == key_id for k in data['data'])


def test_toggle_feature_flag(client, super_admin_context):
    res = client.patch('/api/super-admin/settings/feature-flags/beta_qc_charts', headers=super_admin_context['headers'], json={
        "enabled": True
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data['data']['enabled'] is True


def test_maintenance_mode_status(client, app):
    with app.app_context():
        s = PlatformSettings.query.order_by(PlatformSettings.id.asc()).first()
        if not s:
            s = PlatformSettings()
            db.session.add(s)
        s.maintenance_mode = False
        db.session.commit()

    # 1. Default (off)
    res = client.get('/api/auth/maintenance-status')
    assert res.status_code == 200
    data = res.get_json()
    assert data['maintenance_mode'] is False

    # 2. Enabled
    with app.app_context():
        s = PlatformSettings.query.order_by(PlatformSettings.id.asc()).first()
        s.maintenance_mode = True
        s.maintenance_settings = {"maintenance_message": "System is updating", "estimated_completion": "30 mins"}
        db.session.commit()

    try:
        res = client.get('/api/auth/maintenance-status')
        assert res.status_code == 200
        data = res.get_json()
        assert data['maintenance_mode'] is True
        assert data['message'] == "System is updating"
        assert data['eta'] == "30 mins"
    finally:
        # Reset
        with app.app_context():
            s = PlatformSettings.query.order_by(PlatformSettings.id.asc()).first()
            s.maintenance_mode = False
            db.session.commit()


def test_organization_maintenance_mode(client, auth_context, app):
    from flask_jwt_extended import create_access_token
    org_id = auth_context['org_id']
    admin_headers = auth_context['headers']

    # 1. Turn on organization maintenance mode via admin settings endpoint
    res = client.put('/api/admin/org-settings', headers=admin_headers, json={'maintenance_mode': True})
    assert res.status_code == 200

    try:
        # Create a team member in this organization
        with app.app_context():
            tm_role = Role.query.filter_by(name='Team Member').first()
            if not tm_role:
                tm_role = Role(name='Team Member', description='Team Member')
                db.session.add(tm_role)
                db.session.commit()
            uid = uuid.uuid4().hex[:6]
            tm_user = User(
                email=f"tm_{uid}@pytest.org",
                username=f"tm_{uid}",
                full_name="Pytest Team Member",
                org_id=org_id,
                role_id=tm_role.id,
                is_active=True,
                is_verified=True,
                status="Active"
            )
            tm_user.set_password("MemberPass123!")
            db.session.add(tm_user)
            db.session.commit()
            tm_id = tm_user.id
            tm_username = tm_user.username

        tm_token = create_access_token(identity=str(tm_id))
        tm_headers = {'Authorization': f'Bearer {tm_token}', 'Content-Type': 'application/json'}

        # 2. Check /api/auth/maintenance-status for Team Member: maintenance_mode is True, is_exempt is False
        res = client.get('/api/auth/maintenance-status', headers=tm_headers)
        assert res.status_code == 200
        data = res.get_json()
        assert data['maintenance_mode'] is True
        assert data['scope'] == 'organization'
        assert data['is_exempt'] is False

        # 3. Check /api/auth/maintenance-status for Admin: maintenance_mode is True, is_exempt is True
        res = client.get('/api/auth/maintenance-status', headers=admin_headers)
        assert res.status_code == 200
        data = res.get_json()
        assert data['maintenance_mode'] is True
        assert data['scope'] == 'organization'
        assert data['is_exempt'] is True

        # 4. Team Member calls protected API during maintenance: receives 503 MAINTENANCE_MODE
        res = client.get('/api/projects', headers=tm_headers)
        assert res.status_code == 503
        data = res.get_json()
        assert data['code'] == 'MAINTENANCE_MODE'

        # 5. Team Member tries to log in during maintenance: receives 403 MAINTENANCE_MODE
        res = client.post('/api/auth/login', json={'identifier': tm_username, 'password': "MemberPass123!"})
        assert res.status_code == 403
        data = res.get_json()
        assert data['code'] == 'MAINTENANCE_MODE'

    finally:
        # Reset organization maintenance mode
        client.put('/api/admin/org-settings', headers=admin_headers, json={'maintenance_mode': False})


def test_realtime_alerts(client, super_admin_context, app):
    uid = uuid.uuid4().hex[:6]
    with app.app_context():
        expiring_org = Organization(
            name=f"Expiring Corp {uid}",
            org_code=f"EXP_{uid}".upper(),
            email=f"admin_{uid}@expiring.com",
            subscription_plan="Professional",
            subscription_status="Active",
            license_expiry_date=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=3)
        )
        db.session.add(expiring_org)
        db.session.commit()

    res = client.get('/api/super-admin/alerts', headers=super_admin_context['headers'])
    assert res.status_code == 200
    data = res.get_json()
    assert data['status'] == 'success'
    assert data['count'] > 0

    alert_titles = [a['title'] for a in data['data']]
    assert any(f"Expiring Corp {uid}" in t for t in alert_titles)
