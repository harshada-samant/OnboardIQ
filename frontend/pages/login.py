"""
frontend/pages/login.py
-----------------------
Light-themed login page matching the reference image.
- Slanted 3D onboarding pipeline illustration with 6 stages (Discovery -> Planning).
- Beautiful floating cards and dotted connection paths.
- Accurate text copy, form icons, alignment, and spacing.
- Guarantees 100vh viewport fitting (no scrollbars).
"""

from fastapi.responses import RedirectResponse
from nicegui import app, ui
from frontend.logo import LOGO_38, LOGO_46

@ui.page('/login')
def login_page():
    # If already authenticated, redirect to dashboard
    if app.storage.user.get('authenticated', False):
        return RedirectResponse('/')

    ui.add_head_html('''
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
      *, *::before, *::after { box-sizing: border-box; }
      html, body {
        margin: 0; padding: 0;
        width: 100vw; height: 100vh;
        overflow: hidden !important;
        font-family: 'Inter', sans-serif;
        background: #e9f0fa;
      }
      /* NiceGUI root wrapper — make it full screen with no scroll */
      body > div, #q-app, .q-page-container, .q-page {
        height: 100vh !important;
        overflow: hidden !important;
      }

      /* ── Full-page layout ── */
      #login-root {
        position: fixed; inset: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        background: #e9f0fa;
        overflow: hidden;
      }

      /* Soft background abstract circles (matches reference image) */
      .bg-circle-1 {
        position: absolute;
        border: 1.5px solid rgba(255,255,255,0.7);
        border-radius: 50%;
        width: 650px; height: 650px;
        left: -180px; top: -120px;
        pointer-events: none;
        z-index: 0;
      }
      .bg-circle-2 {
        position: absolute;
        border: 1.5px solid rgba(255,255,255,0.5);
        border-radius: 50%;
        width: 850px; height: 850px;
        right: -280px; bottom: -200px;
        pointer-events: none;
        z-index: 0;
      }

      /* Dot grids in corners */
      .dot-grid {
        position: absolute;
        width: 96px;
        height: 96px;
        background-image: radial-gradient(#cbd5e1 1.5px, transparent 1.5px);
        background-size: 12px 12px;
        opacity: 0.55;
        z-index: 0;
      }
      .dot-grid.top-left { top: 32px; left: 32px; }
      .dot-grid.bottom-left { bottom: 32px; left: 32px; }

      /* ── Two-panel Card Container ── */
      .login-container {
        display: flex;
        width: 1020px;
        height: 680px;
        background: white;
        border-radius: 24px;
        box-shadow: 0 25px 50px -12px rgba(15, 23, 42, 0.12),
                    0 0 1px 1px rgba(15, 23, 42, 0.05);
        border: 1px solid rgba(226, 232, 240, 0.8);
        overflow: hidden;
        z-index: 2;
      }

      /* ── LEFT PANEL ── */
      .left-panel {
        width: 50%;
        background: linear-gradient(135deg, #f8fafc 0%, #edf2f9 100%);
        padding: 44px 48px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        position: relative;
        overflow: hidden;
        border-right: 1px solid #edf2f7;
      }

      .brand-row {
        display: flex;
        align-items: center;
        gap: 10px;
      }
      .brand-name {
        font-size: 1.45rem;
        font-weight: 700;
        color: #0f172a;
        letter-spacing: -0.3px;
      }
      .brand-name span { color: #2563eb; }

      .tagline-group {
        margin-top: 10px;
      }
      .tagline {
        font-size: 2.1rem;
        font-weight: 800;
        color: #0f172a;
        line-height: 1.25;
        margin: 0 0 12px 0;
      }
      .tagline .blue { color: #2563eb; }

      .desc {
        font-size: 0.92rem;
        color: #475569;
        line-height: 1.6;
        margin: 0;
      }

      /* 3D Pipeline Section */
      .pipeline-3d-wrap {
        perspective: 1200px;
        position: relative;
        width: 100%;
        height: 280px;
        display: flex;
        align-items: center;
        justify-content: center;
        margin-top: auto;
      }
      
      /* Subtle dark platform anchor at the bottom of 3D space */
      .pipeline-base {
        position: absolute;
        width: 82%;
        height: 20px;
        background: #cbd5e1;
        border-radius: 50%;
        transform: rotateX(75deg);
        bottom: 12px;
        filter: blur(4px);
        opacity: 0.45;
        z-index: 0;
      }

      .pipeline-screen {
        width: 88%;
        background: white;
        border-radius: 12px;
        border: 1px solid rgba(226, 232, 240, 0.9);
        box-shadow: -15px 20px 40px rgba(15, 23, 42, 0.12),
                    0 4px 6px rgba(15, 23, 42, 0.04);
        padding: 16px 20px;
        transform: rotateX(22deg) rotateY(-22deg) rotateZ(5deg);
        transform-style: preserve-3d;
        position: relative;
        z-index: 1;
      }

      .pipeline-titlebar {
        display: flex;
        align-items: center;
        gap: 5px;
        border-bottom: 1px solid #f1f5f9;
        padding-bottom: 8px;
        margin-bottom: 16px;
      }
      .titlebar-dot {
        width: 7px; height: 7px;
        border-radius: 50%;
        background: #cbd5e1;
      }
      .pipeline-label {
        font-size: 0.72rem;
        font-weight: 700;
        color: #0f172a;
        margin-left: 10px;
      }

      .pipeline-steps {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        position: relative;
        padding: 10px 0;
        z-index: 1;
      }
      .pipeline-line {
        position: absolute;
        top: 20px;
        left: 10px; right: 10px;
        height: 3px;
        background: linear-gradient(to right, #2563eb 0%, #2563eb 80%, #cbd5e1 80%, #cbd5e1 100%);
        z-index: 0;
      }

      .pipeline-step {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 6px;
        z-index: 1;
      }
      .step-dot-done {
        width: 18px; height: 18px;
        border-radius: 50%;
        background: #2563eb;
        display: flex; align-items: center; justify-content: center;
        box-shadow: 0 0 0 3px rgba(37,99,235,0.15);
      }
      .step-dot-pending {
        width: 18px; height: 18px;
        border-radius: 50%;
        background: white;
        border: 3px solid #cbd5e1;
      }
      .step-name {
        font-size: 0.58rem;
        color: #334155;
        font-weight: 600;
        text-align: center;
        white-space: nowrap;
      }
      .step-name.pending { color: #94a3b8; }

      /* Floating cards */
      .float-card {
        position: absolute;
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 3;
      }
      .float-card.pie { width: 44px; height: 44px; top: 18px; left: -14px; transform: rotateZ(-8deg); }
      .float-card.doc { width: 44px; height: 44px; bottom: 8px; left: 10px; transform: rotateZ(10deg); }
      .float-card.shield { width: 44px; height: 44px; bottom: -12px; right: 54px; transform: rotateZ(-6deg); }
      .float-card.bar { width: 44px; height: 44px; top: 58px; right: -14px; transform: rotateZ(8deg); }

      /* ── RIGHT PANEL ── */
      .right-panel {
        width: 50%;
        background: white;
        padding: 44px 56px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        position: relative;
      }

      .logo-avatar {
        width: 76px; height: 76px;
        border-radius: 50%;
        background: #eff6ff;
        border: 1.5px solid #bfdbfe;
        display: flex; align-items: center; justify-content: center;
        margin: 0 auto 16px;
      }
      .welcome-title {
        font-size: 1.72rem;
        font-weight: 700;
        color: #0f172a;
        text-align: center;
        margin: 0 0 5px 0;
      }
      .welcome-sub {
        font-size: 0.88rem;
        color: #64748b;
        text-align: center;
        margin: 0 0 28px 0;
      }

      /* Form inputs */
      .field-group { margin-bottom: 16px; }
      .field-label {
        display: block;
        font-size: 0.85rem;
        font-weight: 600;
        color: #0f172a;
        margin-bottom: 6px;
      }
      .field-wrap {
        display: flex;
        align-items: center;
        border: 1.5px solid #cbd5e1;
        border-radius: 9px;
        background: white;
        padding: 0 14px;
        height: 48px;
        transition: all 0.15s ease-in-out;
      }
      .field-wrap:focus-within {
        border-color: #2563eb;
        box-shadow: 0 0 0 3.5px rgba(37,99,235,0.12);
      }
      .field-wrap svg { flex-shrink: 0; color: #64748b; }
      .field-wrap input {
        flex: 1;
        border: none; outline: none;
        background: transparent;
        font-size: 0.88rem;
        color: #0f172a;
        font-family: 'Inter', sans-serif;
        padding: 0 10px;
      }
      .field-wrap input::placeholder { color: #94a3b8; }
      .eye-btn {
        background: none; border: none; cursor: pointer;
        padding: 0; color: #64748b; line-height: 0;
      }
      .eye-btn:hover { color: #334155; }

      .forgot-row { text-align: right; margin-top: -8px; margin-bottom: 22px; }
      .forgot-link {
        font-size: 0.85rem;
        font-weight: 600;
        color: #2563eb;
        text-decoration: none;
      }
      .forgot-link:hover { text-decoration: underline; }

      .signin-btn {
        width: 100%;
        height: 48px;
        background: #2563eb;
        color: white;
        border: none;
        border-radius: 9px;
        font-size: 0.95rem;
        font-weight: 700;
        font-family: 'Inter', sans-serif;
        cursor: pointer;
        display: flex; align-items: center; justify-content: center;
        gap: 6px;
        transition: background 0.15s, transform 0.1s;
        margin-bottom: 20px;
      }
      .signin-btn:hover { background: #1d4ed8; }
      .signin-btn:active { transform: scale(0.99); }

      .or-row {
        display: flex; align-items: center; gap: 10px;
        margin-bottom: 18px;
      }
      .or-line { flex: 1; height: 1.5px; background: #f1f5f9; }
      .or-text { font-size: 0.82rem; color: #94a3b8; font-weight: 500; }

      /* Demo Credentials container */
      .demo-box {
        background: #eff6ff;
        border-radius: 12px;
        padding: 14px 18px;
        display: flex;
        align-items: center;
        gap: 14px;
        border: 1px solid rgba(37,99,235,0.06);
      }
      .demo-badge {
        width: 36px; height: 36px;
        background: #dbeafe;
        border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        flex-shrink: 0;
      }
      .demo-content {
        display: flex;
        flex-direction: column;
      }
      .demo-title {
        font-size: 0.85rem;
        font-weight: 700;
        color: #1e40af;
        margin: 0 0 3px 0;
      }
      .demo-creds {
        font-size: 0.78rem;
        color: #1e3a8a;
        margin: 0;
        line-height: 1.5;
        font-weight: 500;
      }
      .demo-creds span {
        color: #1d4ed8;
      }
    </style>
    ''')

    # Render background abstract elements
    ui.html('<div class="bg-circle-1"></div>')
    ui.html('<div class="bg-circle-2"></div>')
    ui.html('<div class="dot-grid top-left"></div>')
    ui.html('<div class="dot-grid bottom-left"></div>')

    # Hidden NiceGUI container for server-side events
    ui.query('body').style('background: #e9f0fa;')

    def try_login():
        user = username_input.value.strip()
        pwd = password_input.value.strip()
        valid_users = {"admin": "adminpassword", "user1": "password123"}
        if user in valid_users and valid_users[user] == pwd:
            app.storage.user['authenticated'] = True
            app.storage.user['username'] = user
            ui.navigate.to('/')
        else:
            ui.notify('Invalid username or password', type='negative', position='top')

    # Render the full login page HTML layout
    ui.html(f'''
    <div id="login-root">
      <div class="login-container">

        <!-- ====== LEFT PANEL ====== -->
        <div class="left-panel">

          <!-- Brand row -->
          <div class="brand-row">
            {LOGO_38}
            <span class="brand-name">Onboard<span>IQ</span></span>
          </div>

          <!-- Taglines -->
          <div class="tagline-group">
            <h1 class="tagline">Intelligent Onboarding.<br><span class="blue">Stronger</span> Outcomes.</h1>
            <p class="desc">OnboardIQ uses AI agents to automate data discovery, profiling, mapping, and readiness&mdash;so you can onboard faster and with confidence.</p>
          </div>

          <!-- 3D Pipeline visual -->
          <div class="pipeline-3d-wrap">
            <div class="pipeline-base"></div>
            
            <div class="pipeline-screen">
              <div class="pipeline-titlebar">
                <div class="titlebar-dot"></div>
                <div class="titlebar-dot"></div>
                <div class="titlebar-dot"></div>
                <span class="pipeline-label">Onboarding Pipeline</span>
              </div>
              
              <div class="pipeline-steps">
                <div class="pipeline-line"></div>

                <div class="pipeline-step">
                  <div class="step-dot-done">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="white" width="10" height="10"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
                  </div>
                  <span class="step-name">Discovery</span>
                </div>

                <div class="pipeline-step">
                  <div class="step-dot-done">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="white" width="10" height="10"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
                  </div>
                  <span class="step-name">Profiling</span>
                </div>

                <div class="pipeline-step">
                  <div class="step-dot-done">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="white" width="10" height="10"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
                  </div>
                  <span class="step-name">Mapping</span>
                </div>

                <div class="pipeline-step">
                  <div class="step-dot-done">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="white" width="10" height="10"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
                  </div>
                  <span class="step-name">Specification</span>
                </div>

                <div class="pipeline-step">
                  <div class="step-dot-done">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="white" width="10" height="10"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
                  </div>
                  <span class="step-name">Readiness</span>
                </div>

                <div class="pipeline-step">
                  <div class="step-dot-pending"></div>
                  <span class="step-name pending">Planning</span>
                </div>
              </div>
            </div>

            <!-- Floating cards (layered in 3D) -->
            <div class="float-card pie">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2" width="22" height="22">
                <path d="M21.21 15.89A10 10 0 1 1 8 2.83"/>
                <path d="M22 12A10 10 0 0 0 12 2v10z" fill="#bfdbfe" stroke="none"/>
              </svg>
            </div>
            
            <div class="float-card doc">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" width="22" height="22">
                <rect x="4" y="3" width="16" height="18" rx="2" fill="#e0f2fe" stroke="#2563eb" stroke-width="1.5"/>
                <line x1="8" y1="8" x2="16" y2="8" stroke="#2563eb" stroke-width="1.5" stroke-linecap="round"/>
                <line x1="8" y1="12" x2="16" y2="12" stroke="#93c5fd" stroke-width="1.5" stroke-linecap="round"/>
                <line x1="8" y1="16" x2="13" y2="16" stroke="#93c5fd" stroke-width="1.5" stroke-linecap="round"/>
              </svg>
            </div>
            
            <div class="float-card shield">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="22" height="22">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" fill="#d1fae5" stroke="#10b981"/>
                <path d="m9 12 2 2 4-4"/>
              </svg>
            </div>
            
            <div class="float-card bar">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" width="22" height="22">
                <rect x="3" y="13" width="4" height="8" rx="1" fill="#93c5fd"/>
                <rect x="10" y="9" width="4" height="12" rx="1" fill="#60a5fa"/>
                <rect x="17" y="5" width="4" height="16" rx="1" fill="#2563eb"/>
              </svg>
            </div>

            <!-- SVG Dotted Connections -->
            <svg class="dotted-lines" viewBox="0 0 400 300" style="position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; z-index: 0;">
              <path d="M 50 140 Q 80 120 120 135" fill="none" stroke="#bfdbfe" stroke-width="1.5" stroke-dasharray="4,4"/>
              <path d="M 75 220 Q 110 200 135 170" fill="none" stroke="#bfdbfe" stroke-width="1.5" stroke-dasharray="4,4"/>
              <path d="M 270 190 Q 300 215 315 230" fill="none" stroke="#bfdbfe" stroke-width="1.5" stroke-dasharray="4,4"/>
              <path d="M 310 120 Q 335 105 365 125" fill="none" stroke="#bfdbfe" stroke-width="1.5" stroke-dasharray="4,4"/>
            </svg>
          </div>
        </div>

        <!-- ====== RIGHT PANEL ====== -->
        <div class="right-panel">

          <!-- Logo avatar -->
          <div class="logo-avatar">
            {LOGO_46}
          </div>

          <h2 class="welcome-title">Welcome back!</h2>
          <p class="welcome-sub">Sign in to your onboarding workspace</p>

          <!-- Username field -->
          <div class="field-group">
            <label class="field-label">Username</label>
            <div class="field-wrap">
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
              </svg>
              <input id="iq-username" type="text" placeholder="Enter your username" autocomplete="username"/>
            </div>
          </div>

          <!-- Password field -->
          <div class="field-group">
            <label class="field-label">Password</label>
            <div class="field-wrap">
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
              </svg>
              <input id="iq-password" type="password" placeholder="Enter your password" autocomplete="current-password"/>
              <button class="eye-btn" onclick="togglePwd()" type="button">
                <svg id="eye-icon" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>
                </svg>
              </button>
            </div>
          </div>

          <!-- Forgot password -->
          <div class="forgot-row">
            <a class="forgot-link" href="#">Forgot password?</a>
          </div>

          <!-- Sign In button -->
          <button class="signin-btn" onclick="doLogin()">
            Sign In
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>
            </svg>
          </button>

          <!-- Or divider -->
          <div class="or-row">
            <div class="or-line"></div>
            <span class="or-text">or</span>
            <div class="or-line"></div>
          </div>

          <!-- Demo credentials -->
          <div class="demo-box">
            <div class="demo-badge">
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
              </svg>
            </div>
            <div class="demo-content">
              <p class="demo-title">Demo Credentials</p>
              <p class="demo-creds">
                &bull; User: <span>admin</span> &nbsp;/&nbsp; Pass: <span>adminpassword</span><br>
                &bull; User: <span>user1</span> &nbsp;/&nbsp; Pass: <span>password123</span>
              </p>
            </div>
          </div>

        </div>
      </div>
    </div>
    ''')

    # Add the client-side JavaScript block to connect interactions
    ui.add_body_html('''
    <script>
      function togglePwd() {
        var inp = document.getElementById('iq-password');
        var ico = document.getElementById('eye-icon');
        if (inp.type === 'password') {
          inp.type = 'text';
          ico.innerHTML = '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>';
        } else {
          inp.type = 'password';
          ico.innerHTML = '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>';
        }
      }

      function doLogin() {
        var u = document.getElementById('iq-username').value.trim();
        var p = document.getElementById('iq-password').value.trim();
        // Pass values to hidden NiceGUI inputs then trigger login
        var nu = document.getElementById('iq-nicegui-user');
        var np = document.getElementById('iq-nicegui-pass');
        if (nu) { nu.value = u; nu.dispatchEvent(new Event('input')); }
        if (np) { np.value = p; np.dispatchEvent(new Event('input')); }
        setTimeout(function() {
          var btn = document.getElementById('iq-login-btn');
          if (btn) btn.click();
        }, 80);
      }

      // Also support Enter key
      document.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') doLogin();
      });
    </script>
    ''')

    # Hidden NiceGUI elements that bridge JS -> Python
    with ui.element('div').style('position:absolute; opacity:0; pointer-events:none; width:1px; height:1px; overflow:hidden;'):
        username_input = ui.input().props('id=iq-nicegui-user')
        password_input = ui.input().props('id=iq-nicegui-pass')
        ui.button(on_click=try_login).props('id=iq-login-btn')
