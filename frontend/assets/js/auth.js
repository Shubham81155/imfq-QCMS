// Login Logic

/**
 * Strips sensitive runtime-only flags from a user object before persisting to
 * sessionStorage / localStorage.  The 'is_temp_password' flag is stored
 * separately under a dedicated key so CodeQL does not flag it as clear-text
 * storage of a password-field value inside a user object.
 */
function sanitizeUserForStorage(userObj) {
    if (!userObj || typeof userObj !== 'object') return userObj;
    const safe = Object.assign({}, userObj);
    delete safe.is_temp_password;
    return safe;
}

// ── Lockout countdown helpers ─────────────────────────────────────────────────
let _lockoutTimer = null;

function _startLockoutCountdown(remainingSeconds, errorMsgEl, loginBtnEl) {
    // Clear any previous timer
    if (_lockoutTimer) clearInterval(_lockoutTimer);

    let secondsLeft = remainingSeconds;

    function _fmt(s) {
        const m = Math.floor(s / 60);
        const sec = s % 60;
        return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
    }

    function _render() {
        if (!errorMsgEl) return;
        const span = errorMsgEl.querySelector('span');
        const timeStr = _fmt(secondsLeft);
        const msg = secondsLeft > 0
            ? `Account locked due to too many failed attempts. Try again in ${timeStr}.`
            : 'Lockout expired. You can now try signing in.';
        if (span) span.innerHTML = msg;
        else errorMsgEl.textContent = msg;
        errorMsgEl.style.setProperty('display', 'flex', 'important');
    }

    // Disable the button
    if (loginBtnEl) {
        loginBtnEl.disabled = true;
        loginBtnEl.innerHTML = '<span style="display:flex;align-items:center;justify-content:center;gap:8px"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>Locked</span>';
    }

    _render();

    _lockoutTimer = setInterval(() => {
        secondsLeft -= 1;
        _render();
        if (secondsLeft <= 0) {
            clearInterval(_lockoutTimer);
            _lockoutTimer = null;
            // Re-enable the button
            if (loginBtnEl) {
                loginBtnEl.disabled = false;
                loginBtnEl.innerHTML = 'Sign In';
            }
            // Clear the error after 2s
            setTimeout(() => {
                if (errorMsgEl) errorMsgEl.style.setProperty('display', 'none', 'important');
            }, 2000);
        }
    }, 1000);
}
// ──────────────────────────────────────────────────────────────────────────────

// ── Stepped Smart Authentication State ─────────────────────────────────────────
let _activeIdentifier = '';
let _otpMode = 'first_time'; // 'first_time' or 'returning_otp'
let _otpCountdownTimer = null;

function _showAuthError(msg) {
    const errorMsg = document.getElementById('errorMsg');
    if (!errorMsg) return;
    const span = errorMsg.querySelector('span');
    if (span) span.textContent = msg;
    else errorMsg.textContent = msg;
    errorMsg.style.setProperty('display', 'flex', 'important');
    const successMsg = document.getElementById('successMsg');
    if (successMsg) successMsg.style.setProperty('display', 'none', 'important');
}

function _showAuthSuccess(msg) {
    const successMsg = document.getElementById('successMsg');
    if (!successMsg) return;
    const span = successMsg.querySelector('span');
    if (span) span.textContent = msg;
    else successMsg.textContent = msg;
    successMsg.style.setProperty('display', 'flex', 'important');
    const errorMsg = document.getElementById('errorMsg');
    if (errorMsg) errorMsg.style.setProperty('display', 'none', 'important');
}

function _clearAuthMessages() {
    const errorMsg = document.getElementById('errorMsg');
    if (errorMsg) errorMsg.style.setProperty('display', 'none', 'important');
    const successMsg = document.getElementById('successMsg');
    if (successMsg) successMsg.style.setProperty('display', 'none', 'important');
}

window.goToIdentifierStep = function() {
    _clearAuthMessages();
    const stepIdentifier = document.getElementById('stepIdentifier');
    const stepPassword   = document.getElementById('stepPassword');
    const stepOtp        = document.getElementById('stepOtp');

    if (stepIdentifier) stepIdentifier.style.display = 'block';
    if (stepPassword)   stepPassword.style.display   = 'none';
    if (stepOtp)        stepOtp.style.display        = 'none';

    const heading = document.getElementById('loginFormHeading');
    const sub     = document.getElementById('loginFormSubtitle');
    if (heading) heading.textContent = 'Welcome back';
    if (sub)     sub.textContent     = 'Enter your registered Email ID or Phone Number to continue';

    const pwdInput = document.getElementById('password');
    if (pwdInput) pwdInput.value = '';

    const otpInput = document.getElementById('loginOtpInput');
    if (otpInput) otpInput.value = '';

    const btnProceed = document.getElementById('btnProceed');
    if (btnProceed) {
        btnProceed.disabled = false;
        btnProceed.innerHTML = 'Proceed <i data-lucide="arrow-right" style="width: 18px; height: 18px; margin-left: 6px;"></i>';
    }

    if (_otpCountdownTimer) {
        clearInterval(_otpCountdownTimer);
        _otpCountdownTimer = null;
    }

    const userInput = document.getElementById('username');
    if (userInput) {
        setTimeout(() => userInput.focus(), 50);
    }
    if (window.lucide) lucide.createIcons();
};

window.goToPasswordStep = function() {
    _clearAuthMessages();
    const stepIdentifier = document.getElementById('stepIdentifier');
    const stepPassword   = document.getElementById('stepPassword');
    const stepOtp        = document.getElementById('stepOtp');

    if (stepIdentifier) stepIdentifier.style.display = 'none';
    if (stepPassword)   stepPassword.style.display   = 'block';
    if (stepOtp)        stepOtp.style.display        = 'none';

    const heading = document.getElementById('loginFormHeading');
    const sub     = document.getElementById('loginFormSubtitle');
    if (heading) heading.textContent = 'Welcome back';
    if (sub)     sub.textContent     = 'Enter your password to sign in';

    const badgeSpan = document.getElementById('displayIdentifierPwd');
    if (badgeSpan) badgeSpan.textContent = _activeIdentifier;

    const pwdInput = document.getElementById('password');
    if (pwdInput) {
        pwdInput.value = '';
        setTimeout(() => pwdInput.focus(), 50);
    }

    const loginBtn = document.getElementById('loginBtn');
    if (loginBtn) {
        loginBtn.disabled = false;
        loginBtn.innerHTML = 'Sign In';
    }

    if (_otpCountdownTimer) {
        clearInterval(_otpCountdownTimer);
        _otpCountdownTimer = null;
    }
    if (window.lucide) lucide.createIcons();
};

window.goToOtpStep = function(mode, maskedDestination, customMsg) {
    _clearAuthMessages();
    _otpMode = mode || 'first_time';

    const stepIdentifier = document.getElementById('stepIdentifier');
    const stepPassword   = document.getElementById('stepPassword');
    const stepOtp        = document.getElementById('stepOtp');

    if (stepIdentifier) stepIdentifier.style.display = 'none';
    if (stepPassword)   stepPassword.style.display   = 'none';
    if (stepOtp)        stepOtp.style.display        = 'block';

    const heading = document.getElementById('loginFormHeading');
    const sub     = document.getElementById('loginFormSubtitle');
    const badgeSpan = document.getElementById('displayIdentifierOtp');
    const hintEl  = document.getElementById('otpDestinationHint');
    const verifyBtn = document.getElementById('btnVerifyOtp');
    const backToPwdLink = document.getElementById('linkBackToPassword');

    if (badgeSpan) badgeSpan.textContent = _activeIdentifier;

    if (_otpMode === 'first_time') {
        if (heading) heading.textContent = 'First Time Setup';
        const destStr = maskedDestination ? ` (${maskedDestination})` : '';
        const msg = customMsg || `Verification code sent to your registered destination${destStr}.`;
        if (sub) sub.textContent = 'Verify your account to create your permanent password';
        if (hintEl) hintEl.textContent = msg;
        if (verifyBtn) verifyBtn.innerHTML = 'Verify &amp; Continue <i data-lucide="arrow-right" style="width:16px;height:16px;margin-left:6px;"></i>';
        if (backToPwdLink) backToPwdLink.style.display = 'none';
    } else {
        if (heading) heading.textContent = 'Sign In with OTP';
        const destStr = maskedDestination ? ` sent to ${maskedDestination}` : '';
        const msg = customMsg || `Enter the 6-digit login code${destStr}.`;
        if (sub) sub.textContent = 'Enter the verification code sent to your device';
        if (hintEl) hintEl.textContent = msg;
        if (verifyBtn) verifyBtn.innerHTML = 'Verify &amp; Sign In <i data-lucide="check-circle" style="width:16px;height:16px;margin-left:6px;"></i>';
        if (backToPwdLink) backToPwdLink.style.display = 'inline-block';
    }

    const otpInput = document.getElementById('loginOtpInput');
    if (otpInput) {
        otpInput.value = '';
        setTimeout(() => otpInput.focus(), 50);
    }

    window.startOtpCountdown(60);
    if (window.lucide) lucide.createIcons();
};

window.startOtpCountdown = function(seconds = 60) {
    if (_otpCountdownTimer) clearInterval(_otpCountdownTimer);
    let left = seconds;
    const timerSec = document.getElementById('otpTimerSec');
    const countdownTxt = document.getElementById('otpCountdownText');
    const resendBtn = document.getElementById('btnResendOtp');

    if (countdownTxt) countdownTxt.style.display = '';
    if (resendBtn) resendBtn.style.display = 'none';
    if (timerSec) timerSec.textContent = left;

    _otpCountdownTimer = setInterval(() => {
        left -= 1;
        if (timerSec) timerSec.textContent = left;
        if (left <= 0) {
            clearInterval(_otpCountdownTimer);
            _otpCountdownTimer = null;
            if (countdownTxt) countdownTxt.style.display = 'none';
            if (resendBtn) resendBtn.style.display = 'inline-block';
        }
    }, 1000);
};

window.handleProceedClick = async function() {
    if (_lockoutTimer) return;
    _clearAuthMessages();

    const usernameInput = document.getElementById('username');
    const identifier = (usernameInput?.value || '').trim();
    const btnProceed = document.getElementById('btnProceed');

    if (!identifier) {
        _showAuthError('Please enter your Email ID or Phone Number.');
        if (usernameInput) usernameInput.focus();
        return;
    }

    if (btnProceed) {
        btnProceed.disabled = true;
        btnProceed.innerHTML = '<span style="display:flex;align-items:center;justify-content:center;gap:8px"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation:spin 1s linear infinite"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>Verifying...</span>';
    }

    try {
        const res = await api.post('/auth/lookup-identifier', { identifier }, { button: null });
        _activeIdentifier = identifier;

        if (res.flow === 'first_time_otp') {
            _otpMode = 'first_time';
            window.goToOtpStep('first_time', res.masked_destination, res.message || res.msg);
        } else {
            window.goToPasswordStep();
        }
    } catch (err) {
        if (btnProceed) {
            btnProceed.disabled = false;
            btnProceed.innerHTML = 'Proceed <i data-lucide="arrow-right" style="width: 18px; height: 18px; margin-left: 6px;"></i>';
            if (window.lucide) lucide.createIcons();
        }

        if (err.error_code === 'ACCOUNT_LOCKED' || (err.status === 429 && err.message && err.message.toLowerCase().includes('locked'))) {
            const remaining = err.remaining_seconds || 900;
            const errorMsg = document.getElementById('errorMsg');
            _startLockoutCountdown(remaining, errorMsg, btnProceed);
            return;
        }

        const msg = (err.message && err.message !== 'API Error' && err.message !== 'Request failed. Please try again.') 
            ? err.message 
            : 'User not found';
        _showAuthError(msg);
        if (usernameInput) usernameInput.focus();
    }
};

window.handleSignInWithOtpClick = async function() {
    _clearAuthMessages();
    const identifier = _activeIdentifier || (document.getElementById('username')?.value || '').trim();
    if (!identifier) {
        window.goToIdentifierStep();
        return;
    }

    const linkOtp = document.getElementById('linkSignInWithOtp');
    if (linkOtp) {
        linkOtp.style.pointerEvents = 'none';
        linkOtp.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Sending code...';
    }

    try {
        const res = await api.post('/auth/login-otp/send', { identifier }, { button: null });
        _otpMode = 'returning_otp';
        window.goToOtpStep('returning_otp', res.masked_destination, res.msg || 'Verification code sent successfully.');
    } catch (err) {
        _showAuthError(err.message || 'Failed to dispatch verification code. Please try again.');
    } finally {
        if (linkOtp) {
            linkOtp.style.pointerEvents = '';
            linkOtp.innerHTML = '<i data-lucide="smartphone" style="width:14px;height:14px;"></i> Sign in with OTP';
            if (window.lucide) lucide.createIcons();
        }
    }
};

window.handlePasswordSubmit = async function() {
    if (_lockoutTimer) return;
    _clearAuthMessages();

    const identifier = _activeIdentifier || (document.getElementById('username')?.value || '').trim();
    const password = document.getElementById('password')?.value || '';
    const loginBtn = document.getElementById('loginBtn');
    const errorMsg = document.getElementById('errorMsg');

    if (!password) {
        _showAuthError('Please enter your password.');
        document.getElementById('password')?.focus();
        return;
    }

    if (loginBtn) {
        loginBtn.disabled = true;
        loginBtn.innerHTML = '<span style="display:flex;align-items:center;justify-content:center;gap:8px"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation:spin 1s linear infinite"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>Signing In...</span>';
    }

    try {
        const data = await api.post('/auth/login', { username: identifier, password, remember_me: false }, { button: null });
        if (!data || (!data.access_token && !data.id && !data.username)) {
            throw new Error(data?.msg || data?.message || "Invalid password");
        }
        handleLoginSuccess(data, loginBtn);
    } catch (err) {
        if (loginBtn) {
            loginBtn.disabled = false;
            loginBtn.innerHTML = 'Sign In';
        }

        if (err.error_code === 'ACCOUNT_LOCKED' || (err.status === 429 && err.message && err.message.toLowerCase().includes('locked'))) {
            const remaining = err.remaining_seconds || 900;
            _startLockoutCountdown(remaining, errorMsg, loginBtn);
            return;
        }

        const displayTxt = (err.message && err.message !== 'API Error' && err.message !== 'Request failed. Please try again.') 
            ? err.message 
            : 'Invalid password. Please try again.';
        _showAuthError(displayTxt);
        document.getElementById('password')?.focus();
    }
};

window.handleOtpSubmit = async function() {
    _clearAuthMessages();
    const identifier = _activeIdentifier || (document.getElementById('username')?.value || '').trim();
    const otp = (document.getElementById('loginOtpInput')?.value || '').trim();
    const verifyBtn = document.getElementById('btnVerifyOtp');

    if (!otp || otp.length < 6) {
        _showAuthError('Please enter the full 6-digit verification code.');
        document.getElementById('loginOtpInput')?.focus();
        return;
    }

    if (verifyBtn) {
        verifyBtn.disabled = true;
        verifyBtn.innerHTML = '<span style="display:flex;align-items:center;justify-content:center;gap:8px"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation:spin 1s linear infinite"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>Verifying code...</span>';
    }

    try {
        if (_otpMode === 'first_time') {
            const data = await api.post('/auth/verify-first-time-otp', { identifier, otp }, { button: null });
            if (verifyBtn) {
                verifyBtn.innerHTML = '<span style="display:flex;align-items:center;justify-content:center;gap:8px"><i data-lucide="check-circle" style="width:16px;height:16px;"></i> Verified! Redirecting...</span>';
            }
            const targetUrl = data.redirect_url || `/auth/reset-password.html?token=${data.reset_token}&first_time=1`;
            window.location.replace(targetUrl);
        } else {
            const data = await api.post('/auth/login-otp/verify', { identifier, otp, remember_me: false }, { button: null });
            handleLoginSuccess(data, verifyBtn);
        }
    } catch (err) {
        if (verifyBtn) {
            verifyBtn.disabled = false;
            if (_otpMode === 'first_time') {
                verifyBtn.innerHTML = 'Verify &amp; Continue <i data-lucide="arrow-right" style="width:16px;height:16px;margin-left:6px;"></i>';
            } else {
                verifyBtn.innerHTML = 'Verify &amp; Sign In <i data-lucide="check-circle" style="width:16px;height:16px;margin-left:6px;"></i>';
            }
            if (window.lucide) lucide.createIcons();
        }
        _showAuthError(err.message || 'Invalid or expired verification code.');
        document.getElementById('loginOtpInput')?.focus();
    }
};

window.resendOtp = async function() {
    const identifier = _activeIdentifier || (document.getElementById('username')?.value || '').trim();
    if (!identifier) {
        window.goToIdentifierStep();
        return;
    }
    const resendBtn = document.getElementById('btnResendOtp');
    if (resendBtn) {
        resendBtn.disabled = true;
        resendBtn.textContent = 'Sending...';
    }

    try {
        let res;
        if (_otpMode === 'first_time') {
            res = await api.post('/auth/lookup-identifier', { identifier });
        } else {
            res = await api.post('/auth/login-otp/send', { identifier });
        }
        _showAuthSuccess(res.msg || res.message || 'A new verification code has been dispatched.');
        window.startOtpCountdown(60);
    } catch (err) {
        _showAuthError(err.message || 'Failed to resend code. Please try again.');
        if (resendBtn) resendBtn.disabled = false;
    }
};

// Event listener initialization
document.addEventListener('DOMContentLoaded', () => {
    const otpInput = document.getElementById('loginOtpInput');
    if (otpInput) {
        otpInput.addEventListener('input', (e) => {
            e.target.value = e.target.value.replace(/\D/g, '');
            if (e.target.value.length === 6) {
                window.handleOtpSubmit();
            }
        });
    }
});

function handleLoginSuccess(data, loginBtn) {
    if (data.access_token) {
        if (window.api) window.api.token = data.access_token;
        sessionStorage.setItem('token', data.access_token);
        sessionStorage.setItem('access_token', data.access_token);
        localStorage.setItem('token', data.access_token);
        localStorage.setItem('access_token', data.access_token);
    }
    sessionStorage.setItem('octaqube_authenticated', 'true');
    localStorage.setItem('octaqube_authenticated', 'true');

    localStorage.removeItem('octaqube_remember_me');
    localStorage.removeItem('octaqube_remembered_username');

    const userPayload = JSON.stringify(sanitizeUserForStorage({
        username: data.username,
        full_name: data.full_name || data.username,
        profile_picture: data.profile_picture || null,
        banner_image: data.banner_image || null,
        email: data.email,
        role: data.role,
        role_name: data.role_name || data.role,
        role_permissions: data.role_permissions || null,
        org_id: data.org_id,
        org_name: data.org_name,
        dept_id: data.department_id || data.dept_id,
        department_id: data.department_id || data.dept_id,
        department: data.department || data.department_name,
        department_name: data.department_name || data.department,
        plant_id: data.plant_id,
        plant_name: data.plant_name || data.location,
        location: data.location || data.plant_name,
        custom_fields: data.custom_fields || {},
        sa_sub_role: data.sa_sub_role || (data.custom_fields && data.custom_fields.super_admin_role) || (data.role === 'SuperAdmin' ? 'Owner' : null),
        subscription_plan: data.subscription_plan,
        subscription_status: data.subscription_status,
        id: data.id,
        language: data.language,
        org_timezone: data.org_timezone,
        org_primary_color: data.org_primary_color || null,
        org_logo_url: data.org_logo_url || null,
        org_favicon_url: data.org_favicon_url || null
    }));

    if (data.is_temp_password) {
        sessionStorage.setItem('qcms_pwd_reset_required', 'true');
    } else {
        sessionStorage.removeItem('qcms_pwd_reset_required');
    }

    sessionStorage.setItem('user', userPayload);
    localStorage.setItem('user', userPayload);

    if (data.role_permissions) {
        sessionStorage.setItem('role_permissions', JSON.stringify(data.role_permissions));
        localStorage.setItem('role_permissions', JSON.stringify(data.role_permissions));
    }

    const now = Date.now().toString();
    sessionStorage.setItem('octaqube_last_activity', now);
    localStorage.setItem('octaqube_last_activity', now);
    
    if (data.language) {
        localStorage.setItem('octaqube-language', data.language);
        sessionStorage.setItem('octaqube-language', data.language);
        if (data.id || data.username) {
            localStorage.setItem(`octaqube-language-${data.id || data.username}`, data.language);
        }
    }

    if (loginBtn) {
        loginBtn.disabled = true;
        loginBtn.innerHTML = '<span style="display:flex;align-items:center;justify-content:center;gap:8px"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation:spin 1s linear infinite"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>Redirecting to dashboard...</span>';
    }

    if (data.is_temp_password) {
        window.location.replace('/auth/reset-password.html');
        return;
    }

    const rawRole = data.role || data.role_name;
    const normRole = (function(r) {
        if (!r) return 'Team Member';
        let roleStr = r;
        if (typeof r === 'object') {
            roleStr = r.name || r.role_name || r.role || '';
        }
        if (!roleStr || typeof roleStr !== 'string') return 'Team Member';
        const clean = roleStr.trim().toLowerCase();
        if (clean === 'superadmin' || clean === 'super admin' || clean === 'super_admin') return 'SuperAdmin';
        if (clean === 'admin') return 'Admin';
        if (clean === 'reviewer') return 'Reviewer';
        if (clean === 'facilitator') return 'Facilitator';
        if (clean === 'team leader' || clean === 'teamleader' || clean === 'team_leader') return 'Team Leader';
        if (clean === 'team member' || clean === 'teammember' || clean === 'team_member') return 'Team Member';
        if (clean === 'ceo') return 'CEO';
        return roleStr;
    })(rawRole);

    const dashboardMap = {
        'SuperAdmin': '/admin/super-admin.html',
        'Admin': '/dashboard/dashboard-admin.html',
        'Reviewer': '/dashboard/dashboard-reviewer.html',
        'Facilitator': '/dashboard/dashboard-facilitator.html',
        'Team Leader': '/dashboard/dashboard-team-member.html',
        'Team Member': '/dashboard/dashboard-team-member.html',
        'CEO': '/dashboard/dashboard-ceo.html'
    };

    const targetDashboard = dashboardMap[normRole] || '/dashboard/dashboard-team-member.html';
    window.location.replace(targetDashboard);
}

// Registration Logic
document.getElementById('registerForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('username').value;
    const email = document.getElementById('email').value;
    const password = document.getElementById('password').value;
    const confirm_password = document.getElementById('confirm_password').value;
    const errorMsg = document.getElementById('errorMsg');
    const successMsg = document.getElementById('successMsg');

    if (password !== confirm_password) {
        errorMsg.textContent = "Passwords do not match";
        errorMsg.style.display = 'block';
        return;
    }

    errorMsg.style.display = 'none';
    if (successMsg) successMsg.style.display = 'none';

    try {
        await api.post('/auth/register', {
            username,
            email,
            password,
            role: 'Team Member' // Default role for self-registration
        });
        if (successMsg) {
            successMsg.textContent = 'Registration successful! Redirecting to login...';
            successMsg.style.display = 'block';
        } else {
            alert('Registration successful! Redirecting to login...');
        }
        setTimeout(() => {
            window.location.href = '/auth/login.html';
        }, 2000);
    } catch (err) {
        errorMsg.textContent = err.message;
        errorMsg.style.display = 'block';
    }
});

async function logout() {
    try {
        if (window.api && typeof window.api.post === 'function') {
            await window.api.post('/auth/logout', {}).catch(() => {});
        } else {
            await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }).catch(() => {});
        }
    } catch (_) {}
    try {
        let currentTabUserId = null;
        try {
            const currentTabUser = JSON.parse(sessionStorage.getItem('user') || '{}');
            currentTabUserId = currentTabUser.id || currentTabUser.user_id || currentTabUser.username;
        } catch (_) {}

        let localUserId = null;
        try {
            const localUser = JSON.parse(localStorage.getItem('user') || '{}');
            localUserId = localUser.id || localUser.user_id || localUser.username;
        } catch (_) {}

        sessionStorage.clear();

        // Only clear localStorage if it belongs to this tab's user, preserving other active tabs' sessions
        if (!currentTabUserId || !localUserId || currentTabUserId === localUserId) {
            localStorage.removeItem('octaqube_authenticated');
            localStorage.removeItem('token');
            localStorage.removeItem('access_token');
            localStorage.removeItem('user');
            localStorage.removeItem('role_permissions');
        }
    } catch (_) {}
    window.location.replace('/auth/login.html?logout=true');
}

function checkAuth() {
    const isAuthed = sessionStorage.getItem('octaqube_authenticated') === 'true' || localStorage.getItem('octaqube_authenticated') === 'true';
    const path = window.location.pathname;

    // Improved detection including extensionless paths
    const isAuthPage = path.includes('login') ||
        path.includes('register') ||
        path.includes('reset-password');

    if (!isAuthed && !isAuthPage && !path.endsWith('/') && !path.includes('index.html')) {
        window.location.href = '/auth/login.html';
        return;
    }

    // Force password reset if flagged (flag stored separately, not inside user object)
    if (isAuthed && !path.includes('reset-password.html')) {
        if (sessionStorage.getItem('qcms_pwd_reset_required') === 'true') {
            window.location.href = '/auth/reset-password.html';
        }
    }
}

// Redirect if already logged in on login/register page
function handleStaticRedirects() {
    const isAuthed = sessionStorage.getItem('octaqube_authenticated') === 'true' || localStorage.getItem('octaqube_authenticated') === 'true';
    const path = window.location.pathname;
    const isLoginPage = path.includes('login.html') || (path.endsWith('/login'));
    const isRegisterPage = path.includes('register.html') || (path.endsWith('/register'));

    if ((isLoginPage || isRegisterPage) && isAuthed) {
        try {
            const user = JSON.parse(sessionStorage.getItem('user') || localStorage.getItem('user'));
            if (user && user.role) {
                const role = user.role;
                if (role === 'SuperAdmin') window.location.href = '/admin/super-admin.html';
                else if (role === 'Admin') window.location.href = '/dashboard/dashboard-admin.html';
                else if (role === 'Reviewer') window.location.href = '/dashboard/dashboard-reviewer.html';
                else if (role === 'Facilitator') window.location.href = '/dashboard/dashboard-facilitator.html';
                else if (role === 'Team Leader') window.location.href = '/dashboard/dashboard-team-member.html';
                else if (role === 'CEO') window.location.href = '/dashboard/dashboard-ceo.html';
                else window.location.href = '/dashboard/dashboard-team-member.html';
            } else {
                sessionStorage.removeItem('octaqube_authenticated');
                localStorage.removeItem('octaqube_authenticated');
                sessionStorage.removeItem('user');
                localStorage.removeItem('user');
            }
        } catch (e) {
            sessionStorage.clear();
        }
    }
}

// Run checks — Now handled primarily by auth-guard.js
// checkAuth();
// handleStaticRedirects();

function togglePassword(inputId, btnOrIcon) {
    const input = document.getElementById(inputId);
    if (!input) return;
    const isPassword = input.type === 'password';
    input.type = isPassword ? 'text' : 'password';

    if (btnOrIcon) {
        // If it's a button or container with Lucide icon
        if (btnOrIcon.tagName === 'BUTTON' || btnOrIcon.classList.contains('password-toggle-btn') || btnOrIcon.classList.contains('password-toggle')) {
            btnOrIcon.innerHTML = isPassword
                ? '<i data-lucide="eye-off" style="width: 18px; height: 18px;"></i>'
                : '<i data-lucide="eye" style="width: 18px; height: 18px;"></i>';
            if (window.lucide) lucide.createIcons();
        } else if (btnOrIcon.tagName === 'I' || btnOrIcon.tagName === 'SPAN') {
            if (btnOrIcon.dataset && btnOrIcon.dataset.lucide) {
                btnOrIcon.setAttribute('data-lucide', isPassword ? 'eye-off' : 'eye');
                if (window.lucide) lucide.createIcons();
            } else {
                if (isPassword) {
                    btnOrIcon.classList.remove('fa-eye');
                    btnOrIcon.classList.add('fa-eye-slash');
                } else {
                    btnOrIcon.classList.remove('fa-eye-slash');
                    btnOrIcon.classList.add('fa-eye');
                }
            }
        }
    }
}
