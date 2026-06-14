# OnboardIQ UI & API Implementation Plan

This document outlines the step-by-step plan for building the OnboardIQ Web UI using NiceGUI and FastAPI.

---

## **Step 1: Basic App Setup & NiceGUI Verification**
*   **Goal:** Initialize the frontend package structure and ensure NiceGUI executes and serves web pages successfully.
*   **Tasks:**
    1.  Add `nicegui` to `requirements.txt`.
    2.  Create the `frontend/` directory structure.
    3.  Write a simple `frontend/main.py` file with a placeholder page to verify server booting.
*   **Verification:** Run `python frontend/main.py` and access `http://localhost:8080` in the browser.

---

## **Step 2: Login Screen & User Session Isolation**
*   **Goal:** Protect the application behind a login screen and partition user data.
*   **Tasks:**
    1.  Create a custom login page styled with a clean, modern light aesthetic.
    2.  Implement dummy credentials authentication (e.g., Username: `admin`, Password: `adminpassword`).
    3.  Utilize NiceGUI's session storage to track logins.
    4.  Configure user workspace folders: if user `admin` logs in, their uploads and outputs are isolated in `outputs/users/admin/` to prevent cross-user data exposure.
*   **Verification:** Verify that incorrect details display warnings, correct details redirect to the dashboard, and a session folder is created.

---

## **Step 3: Core Layout & Navigation Structure**
*   **Goal:** Build the main workspace shell using a split panel layout.
*   **Tasks:**
    1.  **Header:** App title **OnboardIQ**, Target Schema selector dropdown, current user badge, and logout button.
    2.  **Left Workspace (Main Panel):** Tabs for *Ingestion/Discovery*, *Data Profiling*, and *Mappings/Contracts*.
    3.  **Right Sidebar (Dual View):** 
        *   Top Section: The persistent **Conversational Assistant (Chatbot)** panel.
        *   Bottom Section: **Data Directory Browser** displaying uploaded files and generated outputs.
*   **Verification:** Verify that tabs switch properly, panels display on screen, and responsiveness is maintained.

---

## **Step 4: Target Schema Selection & File Upload**
*   **Goal:** Connect ingestion actions directly to the backend.
*   **Tasks:**
    1.  Load target schemas dynamically from the `schemas/` folder. Let the user switch target definitions in the dropdown.
    2.  Implement a drag-and-drop file upload component in the *Ingestion* tab.
    3.  Write the `backend/api.py` endpoint for file uploads.
*   **Verification:** Upload a file and verify it lands in the user-specific upload directory and displays in the right-side file explorer.

---

## **Step 5: Discovery & Data Profiling Dashboard**
*   **Goal:** Render logical tables and data quality issues.
*   **Tasks:**
    1.  Render discovery summaries (tables, fields, key relationships).
    2.  Build a dashboard in the *Data Profiling* tab using color-coded status badges (`Pass`, `Warning`, `Fail`) for null checks, duplicates, and orphan records.
    3.  Display data completeness metrics visually.
*   **Verification:** Run a mock pipeline on uploaded files and verify that discovery tables and quality metrics populate correctly on screen.

---

## **Step 6: Interactive Mapping & Spec Editor**
*   **Goal:** Allow users to view and override mappings in real-time.
*   **Tasks:**
    1.  Build a tabular editor listing logical source columns mapped to target columns.
    2.  Create input boxes/dropdowns next to each field to override the mapping target or transformation logic.
    3.  Save overrides immediately to the user's `user_mappings.json` file, and trigger backend regeneration of the specification document.
*   **Verification:** Modify a mapping in the UI, save it, and verify that the target specification values (such as `nullable` or `validation_rule`) update dynamically on screen.

---

## **Step 7: Bedrock Conversational Assistant Panel Integration**
*   **Goal:** Connect the persistent chat sidebar to the Bedrock assistant.
*   **Tasks:**
    1.  Connect the chat interface to the backend Conversational Assistant agent.
    2.  Let users ask questions about their specific data and get answers.
    3.  Support chat-triggered action commands: if the user types *"map active to is_active"*, verify the backend processes the command, saves the override, and automatically refreshes the mapping UI screen in real-time.
*   **Verification:** Ask a query in the chat sidebar, check for the Bedrock-generated answer, issue a mapping command, and confirm the UI fields update.
