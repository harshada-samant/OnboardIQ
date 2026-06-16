# Migration Specifications and Data Contracts

This document outlines the source-to-target database mapping specifications, types, validation rules, and business constraints.

## Target Entity: User

| Source Field | Target Field | Data Type | Nullable | Validation Rule | Transformation | Business Constraint |
|---|---|---|---|---|---|---|
| user_id | user_id | VARCHAR(50) | False | `IS_UNIQUE` | `direct` | PRIMARY KEY |
| name | full_name | VARCHAR(255) | False | `` | `direct` | NOT NULL |
| role | role | VARCHAR(100) | True | `` | `direct` |  |
| email | email | VARCHAR(255) | True | `` | `direct` |  |
| department | department | VARCHAR(100) | True | `` | `direct` |  |
| active | is_active | BOOLEAN | True | `` | `direct` |  |


## Target Entity: Location

| Source Field | Target Field | Data Type | Nullable | Validation Rule | Transformation | Business Constraint |
|---|---|---|---|---|---|---|
| location_key | location_id | VARCHAR(50) | False | `IS_UNIQUE` | `direct` | PRIMARY KEY |
| loc_name | location_name | VARCHAR(255) | False | `` | `direct` | NOT NULL |
| parent_ref | parent_id | VARCHAR(50) | True | `` | `direct` |  |
| site | site | VARCHAR(100) | True | `` | `direct` |  |
| building | building | VARCHAR(100) | True | `` | `direct` |  |
| floor | floor | VARCHAR(50) | True | `` | `direct` |  |


## Target Entity: Asset

| Source Field | Target Field | Data Type | Nullable | Validation Rule | Transformation | Business Constraint |
|---|---|---|---|---|---|---|
| asset_no | c_asset_id | VARCHAR(50) | False | `IS_UNIQUE` | `uppercase(trim(asset_no))` | PRIMARY KEY |
| asset_name | asset_name | VARCHAR(255) | False | `` | `direct` | NOT NULL |
| loc_code | b_location_id | VARCHAR(50) | True | `` | `direct` |  |
| asset_type | asset_type | VARCHAR(100) | False | `` | `direct` | NOT NULL |
| status | status | VARCHAR(50) | False | `` | `direct` | NOT NULL |
| purchase_date | purchase_date | DATE | True | `IS_DATE` | `cast(purchase_date, 'date')` |  |
| cost | cost | DECIMAL(12,2) | True | `>= 0` | `cast(cost, 'decimal')` |  |


## Target Entity: WorkOrder

| Source Field | Target Field | Data Type | Nullable | Validation Rule | Transformation | Business Constraint |
|---|---|---|---|---|---|---|
| wo_id | wo_id | VARCHAR(50) | False | `IS_UNIQUE` | `direct` | PRIMARY KEY |
| equip_id | asset_id | VARCHAR(50) | False | `FOREIGN_KEY(Asset.c_asset_id)` | `direct` | NOT NULL |
| technician_ref | assigned_user | VARCHAR(50) | True | `FOREIGN_KEY(User.user_id)` | `direct` |  |
| status | status | VARCHAR(50) | False | `` | `direct` | NOT NULL |
| priority | priority | VARCHAR(50) | True | `` | `direct` |  |
| created_date | created_date | DATE | False | `IS_DATE` | `cast(created_date, 'date')` | NOT NULL |
| closed_date | closed_date | DATE | True | `IS_DATE` | `cast(closed_date, 'date')` |  |
| description | description | VARCHAR(255) | True | `` | `direct` |  |

