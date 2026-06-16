# Onboarding Plan

**Migration Readiness Score:** 80.1/100

**Silver Waves:** 2


## Bronze-Silver-Gold Pipeline

### Bronze
Raw ingest layer — all source entities are captured as-is with no wave sequencing.
**Entities:** Assets, Users, WorkOrders
**Raw Ingest Items:**
- Assets (RAW)
- Users (RAW)
- WorkOrders (RAW)

### Silver
Wave-sequenced transformation layer — entities are processed into CSV files in dependency order.
#### Wave 1
**Entities:** Assets, Users
**CSV Files:** D:\onboardingIQ\Onboardiq\outputs\silver\wave_01\assets.csv, D:\onboardingIQ\Onboardiq\outputs\silver\wave_01\users.csv
**Tool Stack:** DuckDB, Pandas
**Wave Rows:** 15
This wave migrates core asset and user data, focusing on establishing a foundational data set for the system. The entities are grouped together as they represent fundamental components of the organization's operational infrastructure.
**Approach:** Full load to CSV, followed by data cleansing and validation to address high null percentages in key fields like location code and status.
**Risk Mitigations:**
- Implement data profiling to thoroughly analyze the null percentages and identify root causes.
- Develop a data imputation strategy for 'loc_code' and 'status' using a combination of default values and business rules.
- Validate the FK candidate 'email' against existing user records to ensure data integrity.
**Risks (4):**
- [MEDIUM] Field 'loc_code' contains high null percentage (20.0%).
- [MEDIUM] Field 'status' contains high null percentage (10.0%).
- [MEDIUM] Field 'email' contains high null percentage (20.0%).
- [MEDIUM] Unresolved FK candidate(s): ['email']
#### Wave 2
**Entities:** WorkOrders
**CSV Files:** D:\onboardingIQ\Onboardiq\outputs\silver\wave_02\workorders.csv
**Tool Stack:** Pandas
**Wave Rows:** 20
This wave focuses on migrating WorkOrder data, a critical component for service management. The wave addresses data quality issues related to closed dates and foreign key relationships.
**Approach:** Full load to CSV, with data cleansing to handle the high null percentage in 'closed_date' and subsequent validation of foreign key relationships.
**Risk Mitigations:**
- Investigate the reason for the high null percentage in 'closed_date' – potential data entry errors or system issues.
- Establish a default 'closed_date' value for WorkOrders that have not been closed, based on business requirements.
- Implement data quality checks to ensure consistency and accuracy of 'status', 'priority', 'created_date', and 'closed_date' fields.
**Risks (2):**
- [MEDIUM] Field 'closed_date' contains high null percentage (55.0%).
- [MEDIUM] Unresolved FK candidate(s): ['status', 'priority', 'created_date', 'closed_date']

### Gold
Target load layer — Silver CSV outputs are loaded into the target database.
#### Load Wave 1
**Source CSVs:** D:\onboardingIQ\Onboardiq\outputs\silver\wave_01\assets.csv, D:\onboardingIQ\Onboardiq\outputs\silver\wave_01\users.csv
**Target Entities:** Assets, Users
**Target:** target_db
**Strategy:** bulk load from Silver CSVs
#### Load Wave 2
**Source CSVs:** D:\onboardingIQ\Onboardiq\outputs\silver\wave_02\workorders.csv
**Target Entities:** WorkOrders
**Target:** target_db
**Strategy:** bulk load from Silver CSVs

## Silver Wave Detail

### Wave 1 — Assets, Users
**CSV Files:** D:\onboardingIQ\Onboardiq\outputs\silver\wave_01\assets.csv, D:\onboardingIQ\Onboardiq\outputs\silver\wave_01\users.csv
**Tool Stack:** DuckDB, Pandas
**Wave Rows:** 15

This wave migrates core asset and user data, focusing on establishing a foundational data set for the system. The entities are grouped together as they represent fundamental components of the organization's operational infrastructure.

**Approach:** Full load to CSV, followed by data cleansing and validation to address high null percentages in key fields like location code and status.

**Risk Mitigations:**
- Implement data profiling to thoroughly analyze the null percentages and identify root causes.
- Develop a data imputation strategy for 'loc_code' and 'status' using a combination of default values and business rules.
- Validate the FK candidate 'email' against existing user records to ensure data integrity.

**Risks (4):**
- [MEDIUM] Field 'loc_code' contains high null percentage (20.0%).
- [MEDIUM] Field 'status' contains high null percentage (10.0%).
- [MEDIUM] Field 'email' contains high null percentage (20.0%).
- [MEDIUM] Unresolved FK candidate(s): ['email']

### Wave 2 — WorkOrders
**CSV Files:** D:\onboardingIQ\Onboardiq\outputs\silver\wave_02\workorders.csv
**Tool Stack:** Pandas
**Wave Rows:** 20

This wave focuses on migrating WorkOrder data, a critical component for service management. The wave addresses data quality issues related to closed dates and foreign key relationships.

**Approach:** Full load to CSV, with data cleansing to handle the high null percentage in 'closed_date' and subsequent validation of foreign key relationships.

**Risk Mitigations:**
- Investigate the reason for the high null percentage in 'closed_date' – potential data entry errors or system issues.
- Establish a default 'closed_date' value for WorkOrders that have not been closed, based on business requirements.
- Implement data quality checks to ensure consistency and accuracy of 'status', 'priority', 'created_date', and 'closed_date' fields.

**Risks (2):**
- [MEDIUM] Field 'closed_date' contains high null percentage (55.0%).
- [MEDIUM] Unresolved FK candidate(s): ['status', 'priority', 'created_date', 'closed_date']
