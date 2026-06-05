# Migration Specifications and Data Contracts

This document outlines the source-to-target database mapping specifications, types, validation rules, and business constraints.

## Target Entity: User

| Source Field | Target Field | Data Type | Nullable | Validation Rule | Transformation | Business Constraint |
|---|---|---|---|---|---|---|
| user_id | user_id | VARCHAR(50) | False | `IS_UNIQUE` | `direct` | PRIMARY KEY |
| name | full_name | VARCHAR(255) | False | `NOT_NULL` | `trim(name)` | NOT NULL |
| role | role | VARCHAR(100) | False | `NOT_NULL` | `direct` | NOT NULL |
| email | email | VARCHAR(255) | True | `REGEX('^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')` | `lower(trim(email))` |  |
| department | department | VARCHAR(100) | False | `NOT_NULL` | `direct` | NOT NULL |
| active | is_active | BOOLEAN | False | `NOT_NULL` | `direct` | NOT NULL |


## Target Entity: Location

| Source Field | Target Field | Data Type | Nullable | Validation Rule | Transformation | Business Constraint |
|---|---|---|---|---|---|---|
| location_key | location_id | VARCHAR(50) | False | `IS_UNIQUE` | `trim(location_key)` | PRIMARY KEY |
| loc_name | location_name | VARCHAR(255) | False | `NOT_NULL` | `trim(loc_name)` | NOT NULL |
| parent_ref | parent_id | VARCHAR(50) | False | `FOREIGN_KEY(Location.location_id)` | `trim(parent_ref)` | FOREIGN KEY(Location.location_id) |
| site | site | VARCHAR(100) | False | `NOT_NULL` | `direct` | NOT NULL |
| building | building | VARCHAR(100) | False | `NOT_NULL` | `direct` | NOT NULL |
| floor | floor | VARCHAR(50) | False | `NOT_NULL` | `direct` | NOT NULL |


## Target Entity: Asset

| Source Field | Target Field | Data Type | Nullable | Validation Rule | Transformation | Business Constraint |
|---|---|---|---|---|---|---|
| asset_no | c_asset_id | VARCHAR(50) | False | `IS_UNIQUE` | `trim(asset_no)` | PRIMARY KEY |
| asset_name | asset_name | VARCHAR(255) | False | `NOT_NULL` | `direct` | NOT NULL |
| loc_code | b_location_id | VARCHAR(50) | True | `FOREIGN_KEY(Location.location_id)` | `trim(loc_code)` | FOREIGN KEY(Location.location_id) |
| asset_type | asset_type | VARCHAR(100) | False | `NOT_NULL` | `direct` | NOT NULL |
| status | status | VARCHAR(50) | False | `NOT_NULL` | `coalesce(status, 'Unknown')` | NOT NULL |
| purchase_date | purchase_date | DATE | False | `IS_DATE` | `cast(purchase_date as date)` | NOT NULL |
| cost | cost | DECIMAL(12,2) | False | `>= 0` | `cast(cost as decimal)` | NOT NULL |


## Target Entity: WorkOrder

| Source Field | Target Field | Data Type | Nullable | Validation Rule | Transformation | Business Constraint |
|---|---|---|---|---|---|---|
| wo_id | wo_id | VARCHAR(50) | False | `IS_UNIQUE` | `direct` | PRIMARY KEY |
| equip_id | asset_id | VARCHAR(50) | False | `FOREIGN_KEY(Asset.c_asset_id)` | `trim(equip_id)` | FOREIGN KEY(Asset.c_asset_id) |
| technician_ref | assigned_user | VARCHAR(50) | True | `FOREIGN_KEY(User.user_id)` | `trim(technician_ref)` | FOREIGN KEY(User.user_id) |
| status | status | VARCHAR(50) | False | `NOT_NULL` | `direct` | NOT NULL |
| priority | priority | VARCHAR(50) | False | `NOT_NULL` | `direct` | NOT NULL |
| created_date | created_date | DATE | False | `IS_DATE` | `cast(created_date as date)` | NOT NULL |
| closed_date | closed_date | DATE | True | `IS_DATE` | `cast(closed_date as date)` |  |
| description | description | VARCHAR(1000) | False | `NOT_NULL` | `direct` | NOT NULL |

