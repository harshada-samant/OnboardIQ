"""
frontend/pages/login.py
-----------------------
Light-themed login page — pure NiceGUI, no raw HTML inputs or JavaScript.
Preserves the original two-panel layout:
  LEFT  → brand, tagline, 3-D pipeline illustration
  RIGHT → logo avatar, welcome text, NiceGUI input fields, sign-in button
"""

import logging

from fastapi.responses import RedirectResponse
from nicegui import app, ui
from frontend.logo import LOGO_38, LOGO_46

logger = logging.getLogger(__name__)


@ui.page('/login')
def login_page():
    # ── If already authenticated redirect to dashboard ──────────────────────
    if app.storage.user.get('authenticated', False):
        return RedirectResponse('/')

    # ── Google Font + global resets ─────────────────────────────────────────
    ui.add_head_html('''
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
      *, *::before, *::after { box-sizing: border-box; }
      html, body {
        margin: 0; padding: 0;
        width: 100vw; height: 100vh;
        overflow: hidden !important;
        font-family: 'Inter', sans-serif;
        background: #f0f4f8;
      }
      body > div, #q-app, .q-layout, .q-page-container, .q-page, .nicegui-content {
        height: 100vh !important;
        overflow: hidden !important;
        padding: 0 !important;
        margin: 0 !important;
        position: relative !important;
      }
      .nicegui-content {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        background: linear-gradient(135deg, #f0f4f8 0%, #e2e8f0 100%) !important;
      }

      /* background decorative circles */
      .bg-circle-1 {
        position: absolute;
        border: 1.5px solid rgba(255,255,255,0.7);
        border-radius: 50%;
        width: 650px; height: 650px;
        left: -180px; top: -120px;
        pointer-events: none; z-index: 0;
      }
      .bg-circle-2 {
        position: absolute;
        border: 1.5px solid rgba(255,255,255,0.5);
        border-radius: 50%;
        width: 850px; height: 850px;
        right: -280px; bottom: -200px;
        pointer-events: none; z-index: 0;
      }

      /* dot grids */
      .dot-grid {
        position: absolute;
        width: 96px; height: 96px;
        background-image: radial-gradient(#cbd5e1 1.5px, transparent 1.5px);
        background-size: 12px 12px;
        opacity: 0.55; z-index: 0;
      }
      .dot-grid.top-left  { top: 32px;    left: 32px; }
      .dot-grid.bot-left  { bottom: 32px; left: 32px; }

      /* ── card container ── */
      .login-container {
        display: flex;
        width: 1040px;
        height: 720px;
        max-width: 95vw;
        max-height: 95vh;
        background: white;
        border-radius: 24px;
        box-shadow: 0 25px 50px -12px rgba(15, 23, 42, 0.08), 
                    0 0 0 1px rgba(15, 23, 42, 0.03);
        overflow: hidden;
        z-index: 2;
        border: 1px solid rgba(226, 232, 240, 0.8);
      }

      /* ── LEFT panel ── */
      .left-panel {
        width: 50%;
        background: linear-gradient(135deg, #f8fafc 0%, #edf2f9 100%);
        padding: 48px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        position: relative;
        overflow: hidden;
        border-right: 1px solid #edf2f7;
      }
      .brand-row { display: flex; align-items: center; gap: 10px; }
      .brand-name { font-size: 1.45rem; font-weight: 700; color: #0f172a; letter-spacing: -0.3px; }
      .brand-name span { color: #2563eb; }
      .tagline-group { margin-top: 10px; }
      .tagline { font-size: 2.1rem; font-weight: 800; color: #0f172a; line-height: 1.25; margin: 0 0 12px; }
      .tagline .blue { color: #2563eb; }
      .desc { font-size: 0.92rem; color: #475569; line-height: 1.6; margin: 0; }

      /* 3-D pipeline */
      .pipeline-3d-wrap {
        perspective: 1200px;
        position: relative;
        width: 100%; height: 260px;
        display: flex; align-items: center; justify-content: center;
        margin-top: auto;
      }
      .pipeline-base {
        position: absolute;
        width: 82%; height: 20px;
        background: #cbd5e1;
        border-radius: 50%;
        transform: rotateX(75deg);
        bottom: 12px;
        filter: blur(4px);
        opacity: 0.45; z-index: 0;
      }
      .pipeline-screen {
        width: 88%;
        background: white;
        border-radius: 12px;
        border: 1px solid rgba(226,232,240,0.9);
        box-shadow: -15px 20px 40px rgba(15,23,42,0.12), 0 4px 6px rgba(15,23,42,0.04);
        padding: 16px 20px;
        transform: rotateX(22deg) rotateY(-22deg) rotateZ(5deg);
        transform-style: preserve-3d;
        position: relative; z-index: 1;
      }
      .pipeline-titlebar {
        display: flex; align-items: center; gap: 5px;
        border-bottom: 1px solid #f1f5f9;
        padding-bottom: 8px; margin-bottom: 16px;
      }
      .titlebar-dot { width: 7px; height: 7px; border-radius: 50%; background: #cbd5e1; }
      .pipeline-label { font-size: 0.72rem; font-weight: 700; color: #0f172a; margin-left: 10px; }
      .pipeline-steps {
        display: flex; align-items: flex-start; justify-content: space-between;
        position: relative; padding: 10px 0; z-index: 1;
      }
      .pipeline-line {
        position: absolute; top: 20px; left: 10px; right: 10px; height: 3px;
        background: linear-gradient(to right, #2563eb 0%, #2563eb 80%, #cbd5e1 80%, #cbd5e1 100%);
        z-index: 0;
      }
      .pipeline-step { display: flex; flex-direction: column; align-items: center; gap: 6px; z-index: 1; }
      .step-dot-done {
        width: 18px; height: 18px; border-radius: 50%; background: #2563eb;
        display: flex; align-items: center; justify-content: center;
        box-shadow: 0 0 0 3px rgba(37,99,235,0.15);
      }
      .step-dot-pending { width: 18px; height: 18px; border-radius: 50%; background: white; border: 3px solid #cbd5e1; }
      .step-name { font-size: 0.58rem; color: #334155; font-weight: 600; text-align: center; white-space: nowrap; }
      .step-name.pending { color: #94a3b8; }

      /* floating accent cards */
      .float-card {
        position: absolute;
        background: white; border: 1px solid #e2e8f0; border-radius: 12px;
        box-shadow: 0 8px 24px rgba(15,23,42,0.08);
        display: flex; align-items: center; justify-content: center;
        z-index: 3;
      }
      .float-card.pie    { width:44px;height:44px; top:18px;   left:-14px;  transform:rotateZ(-8deg); }
      .float-card.doc    { width:44px;height:44px; bottom:8px; left:10px;   transform:rotateZ(10deg); }
      .float-card.shield { width:44px;height:44px; bottom:-12px;right:54px; transform:rotateZ(-6deg); }
      .float-card.bar    { width:44px;height:44px; top:58px;   right:-14px; transform:rotateZ(8deg); }

      /* ── RIGHT panel ── */
      .right-panel {
        width: 50%;
        background: white;
        padding: 48px;
        display: flex; flex-direction: column; justify-content: center;
        position: relative;
      }
      .logo-avatar {
        width: 76px; height: 76px; border-radius: 50%;
        background: #eff6ff; border: 1.5px solid #bfdbfe;
        display: flex; align-items: center; justify-content: center;
        margin: 0 auto 16px;
      }
      .welcome-title { font-size: 1.72rem; font-weight: 700; color: #0f172a; text-align: center; margin: 0 0 5px; }
      .welcome-sub   { font-size: 0.88rem; color: #64748b; text-align: center; margin: 0 0 28px; }

      /* input labels */
      .input-label {
        font-size: 0.82rem !important;
        font-weight: 600 !important;
        color: #1e293b !important;
        margin-bottom: 6px !important;
        display: block !important;
        text-align: left !important;
      }

      /* NiceGUI input override – match original field look */
      .iq-field .q-field__control {
        border: 1.5px solid #cbd5e1 !important;
        border-radius: 9px !important;
        background: white !important;
        height: 48px !important;
        padding: 0 14px !important;
        box-shadow: none !important;
      }
      .iq-field .q-field__control:focus-within {
        border-color: #2563eb !important;
        box-shadow: 0 0 0 3.5px rgba(37,99,235,0.12) !important;
      }
      .iq-field .q-field__prepend {
        padding-right: 10px !important;
        color: #64748b !important;
      }
      .iq-field input { font-size: 0.88rem !important; color: #0f172a !important; font-family: 'Inter', sans-serif !important; }
      .iq-field input::placeholder { color: #94a3b8 !important; }
      /* hide default Quasar underline and errors wrapper */
      .iq-field .q-field__bottom { display: none !important; }
      .iq-field.q-field--highlighted .q-field__control:before,
      .iq-field .q-field__control:before { border: none !important; }

      /* sign-in button */
      .signin-btn {
        width: 100% !important;
        height: 48px !important;
        background: #2563eb !important;
        color: white !important;
        border-radius: 9px !important;
        font-size: 0.95rem !important;
        font-weight: 700 !important;
        font-family: 'Inter', sans-serif !important;
        margin-bottom: 20px !important;
        text-transform: none !important;
        letter-spacing: 0 !important;
      }
      .signin-btn:hover { background: #1d4ed8 !important; }

      .or-row { display: flex; align-items: center; gap: 10px; margin-bottom: 18px; }
      .or-line { flex: 1; height: 1.5px; background: #f1f5f9; }
      .or-text  { font-size: 0.82rem; color: #94a3b8; font-weight: 500; }

      /* demo box */
      .demo-box {
        background: #eff6ff; border-radius: 12px;
        padding: 14px 18px;
        display: flex; align-items: center; gap: 14px;
        border: 1px solid rgba(37,99,235,0.06);
      }
      .demo-badge {
        width: 36px; height: 36px; background: #dbeafe; border-radius: 50%;
        display: flex; align-items: center; justify-content: center; flex-shrink: 0;
      }
      .demo-title { font-size: 0.85rem; font-weight: 700; color: #1e40af; margin: 0 0 3px; }
      .demo-creds { font-size: 0.78rem; color: #1e3a8a; margin: 0; line-height: 1.5; font-weight: 500; }
      .demo-creds span { color: #1d4ed8; }

      .form-container {
        width: 100% !important;
        max-width: 380px !important;
        margin: 0 auto !important;
        display: flex !important;
        flex-direction: column !important;
        justify-content: center !important;
      }

      .forgot-link-wrapper {
        text-align: right !important;
        margin-bottom: 22px !important;
        margin-top: 4px !important;
      }
      .forgot-link {
        font-size: 0.85rem !important;
        font-weight: 600 !important;
        color: #2563eb !important;
        text-decoration: none !important;
      }
      .forgot-link:hover {
        text-decoration: underline !important;
      }
    </style>
    ''')

    ui.query('body').style('background: #f0f4f8;')

    # ── Login handler (pure Python) ─────────────────────────────────────────
    def try_login():
        from backend.workspace import ensure_user_workspace
        from backend.database import authenticate_user
        
        user = username_input.value.strip()
        pwd  = password_input.value.strip()
        
        user_record = authenticate_user(user, pwd)
        if user_record:
            from backend.workspace import archive_chat_history
            archive_chat_history(user_record['username'])
            
            ui.run_javascript("sessionStorage.setItem('session_active', 'true');")
            app.storage.user['authenticated'] = True
            app.storage.user['user_id'] = user_record['id']
            app.storage.user['username'] = user_record['username']
            logger.debug("Authenticated user %s", user_record['username'])
            ensure_user_workspace(user_record['username'])
            import config
            config.set_user_workspace(user_record['username'])
            
            # Configure target schema dynamically for the logged in user
            from backend.schema_manager import configure_user_schema
            configure_user_schema(user_record['id'])
            
            ui.navigate.to('/')
        else:
            ui.notify('Invalid username or password', type='negative', position='top')

    # ── Background decorations ───────────────────────────────────────────────
    ui.html('<div class="bg-circle-1"></div>')
    ui.html('<div class="bg-circle-2"></div>')
    ui.html('<div class="dot-grid top-left"></div>')
    ui.html('<div class="dot-grid bot-left"></div>')

    # ── Two-panel card ───────────────────────────────────────────────────────
    with ui.element('div').classes('login-container'):

        # ════════════════ LEFT PANEL ════════════════
        with ui.element('div').classes('left-panel'):

            # Brand row
            ui.html(f'''
            <div class="brand-row">
              {LOGO_38}
              <span class="brand-name">Onboard<span>IQ</span></span>
            </div>''')

            # Tagline
            ui.html('''
            <div class="tagline-group">
              <h1 class="tagline">Intelligent Onboarding.<br><span class="blue">Stronger</span> Outcomes.</h1>
              <p class="desc">OnboardIQ uses AI agents to automate data discovery, profiling, mapping, and readiness&mdash;so you can onboard faster and with confidence.</p>
            </div>''')

            # 3-D pipeline illustration
            ui.html('''
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

              <!-- floating accent cards -->
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

              <svg viewBox="0 0 400 300" style="position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:0;">
                <path d="M 50 140 Q 80 120 120 135" fill="none" stroke="#bfdbfe" stroke-width="1.5" stroke-dasharray="4,4"/>
                <path d="M 75 220 Q 110 200 135 170" fill="none" stroke="#bfdbfe" stroke-width="1.5" stroke-dasharray="4,4"/>
                <path d="M 270 190 Q 300 215 315 230" fill="none" stroke="#bfdbfe" stroke-width="1.5" stroke-dasharray="4,4"/>
                <path d="M 310 120 Q 335 105 365 125" fill="none" stroke="#bfdbfe" stroke-width="1.5" stroke-dasharray="4,4"/>
              </svg>
            </div>''')

        # ════════════════ RIGHT PANEL ════════════════
        with ui.element('div').classes('right-panel'):
            with ui.element('div').classes('form-container'):

                # Logo avatar
                ui.html(f'<div class="logo-avatar">{LOGO_46}</div>')
                ui.html('<h2 class="welcome-title">Welcome back!</h2>')
                ui.html('<p class="welcome-sub">Sign in to your onboarding workspace</p>')

                # ── Username input ───────────────────────────────────────────────
                ui.label('Username').classes('input-label')
                username_input = (
                    ui.input(placeholder='Enter your username')
                    .classes('iq-field w-full q-mb-md')
                    .props('outlined dense autocomplete=username')
                )
                with username_input.add_slot('prepend'):
                    ui.icon('person').style('font-size: 20px;')

                # ── Password input ───────────────────────────────────────────────
                ui.label('Password').classes('input-label')
                password_input = (
                    ui.input(placeholder='Enter your password', password=True, password_toggle_button=True)
                    .classes('iq-field w-full q-mb-xs')
                    .props('outlined dense autocomplete=current-password')
                )
                with password_input.add_slot('prepend'):
                    ui.icon('lock').style('font-size: 20px;')

                # Forgot password link
                ui.html('''
                <div class="forgot-link-wrapper">
                  <a href="#" class="forgot-link">Forgot password?</a>
                </div>''')

                # ── Sign In button ───────────────────────────────────────────────
                ui.button('Sign In', on_click=try_login) \
                  .classes('signin-btn') \
                  .props('no-caps unelevated icon-right=arrow_forward')

                # Enter key also submits
                username_input.on('keydown.enter', try_login)
                password_input.on('keydown.enter', try_login)



