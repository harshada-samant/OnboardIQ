# Onboarding Plan

**Migration Readiness Score:** 74.7/100

**Silver Waves:** 2


## Bronze-Silver-Gold Pipeline

### Bronze
Raw ingest layer — all source entities are captured as-is with no wave sequencing.
**Entities:** Users, Locations, Assets, WorkOrders
**Raw Ingest Items:**
- Users (RAW)
- Locations (RAW)
- Assets (RAW)
- WorkOrders (RAW)

### Silver
Wave-sequenced transformation layer — entities are processed into CSV files in dependency order.
#### Wave 1
**Entities:** Users, Locations, WorkOrders
**CSV Files:** D:\Hackathon\Onboardiq-merged\Onboardiq-merged\workspaces\users\user1\outputs\silver\wave_01\users.csv, D:\Hackathon\Onboardiq-merged\Onboardiq-merged\workspaces\users\user1\outputs\silver\wave_01\locations.csv, D:\Hackathon\Onboardiq-merged\Onboardiq-merged\workspaces\users\user1\outputs\silver\wave_01\workorders.csv
**Tool Stack:** Pandas
**Wave Rows:** 29
This wave migrates core operational entities – Users, Locations, and WorkOrders – establishing the foundation for field service operations. These entities are grouped together due to their strong interdependencies and common use in downstream processes.
**Approach:** A full load to CSV is recommended, with data cleansing applied during the ETL process to handle null values and resolve FK candidates before loading.
**Risk Mitigations:**
- Implement a data quality rule to flag Users records with missing email addresses for review and potential enrichment.
- Develop a script to populate 'parent_ref' in Locations based on a defined business rule or hierarchy, resolving the FK candidate.
- For WorkOrders, establish a default 'closed_date' value (e.g., current date) or a specific indicator for open orders to address the high null percentage.
**Risks (4):**
- [MEDIUM] Field 'email' contains high null percentage (20.0%).
- [MEDIUM] Unresolved FK candidate(s): ['parent_ref']
- [MEDIUM] Field 'closed_date' contains high null percentage (55.0%).
- [MEDIUM] Unresolved FK candidate(s): ['equip_id', 'technician_ref']
#### Wave 2
**Entities:** Assets
**CSV Files:** D:\Hackathon\Onboardiq-merged\Onboardiq-merged\workspaces\users\user1\outputs\silver\wave_02\assets.csv
**Tool Stack:** Pandas
**Wave Rows:** 10
This wave focuses on migrating Assets, which are critical for tracking equipment and maintenance history. It's separated from Wave 1 due to the complexity of resolving FK constraints and data quality issues specific to asset records.
**Approach:** A full load to CSV is recommended, preceded by a lookup-first approach to validate and correct FK references to Locations before loading.
**Risk Mitigations:**
- Investigate and correct the orphan records in Assets by either updating the FK values or archiving the records if they are invalid.
- Populate the 'loc_code' field in Assets by matching against the Locations table, using a defined mapping or business rule.
- Define a default 'status' value for Assets with missing status information, ensuring consistency and usability.
**Risks (4):**
- [MEDIUM] 1 orphan record(s) (broken FK references)
- [MEDIUM] Field 'loc_code' contains high null percentage (20.0%).
- [MEDIUM] Field 'status' contains high null percentage (10.0%).
- [MEDIUM] Referential integrity check failed: 1 orphan records reference invalid 'Locations.location_key' values.

### Gold
Target load layer — Silver CSV outputs are loaded into the target database.
#### Load Wave 1
**Source CSVs:** D:\Hackathon\Onboardiq-merged\Onboardiq-merged\workspaces\users\user1\outputs\silver\wave_01\users.csv, D:\Hackathon\Onboardiq-merged\Onboardiq-merged\workspaces\users\user1\outputs\silver\wave_01\locations.csv, D:\Hackathon\Onboardiq-merged\Onboardiq-merged\workspaces\users\user1\outputs\silver\wave_01\workorders.csv
**Target Entities:** Users, Locations, WorkOrders
**Target:** target_db
**Strategy:** bulk load from Silver CSVs
#### Load Wave 2
**Source CSVs:** D:\Hackathon\Onboardiq-merged\Onboardiq-merged\workspaces\users\user1\outputs\silver\wave_02\assets.csv
**Target Entities:** Assets
**Target:** target_db
**Strategy:** bulk load from Silver CSVs

## Silver Wave Detail

### Wave 1 — Users, Locations, WorkOrders
**CSV Files:** D:\Hackathon\Onboardiq-merged\Onboardiq-merged\workspaces\users\user1\outputs\silver\wave_01\users.csv, D:\Hackathon\Onboardiq-merged\Onboardiq-merged\workspaces\users\user1\outputs\silver\wave_01\locations.csv, D:\Hackathon\Onboardiq-merged\Onboardiq-merged\workspaces\users\user1\outputs\silver\wave_01\workorders.csv
**Tool Stack:** Pandas
**Wave Rows:** 29

This wave migrates core operational entities – Users, Locations, and WorkOrders – establishing the foundation for field service operations. These entities are grouped together due to their strong interdependencies and common use in downstream processes.

**Approach:** A full load to CSV is recommended, with data cleansing applied during the ETL process to handle null values and resolve FK candidates before loading.

**Risk Mitigations:**
- Implement a data quality rule to flag Users records with missing email addresses for review and potential enrichment.
- Develop a script to populate 'parent_ref' in Locations based on a defined business rule or hierarchy, resolving the FK candidate.
- For WorkOrders, establish a default 'closed_date' value (e.g., current date) or a specific indicator for open orders to address the high null percentage.

**Risks (4):**
- [MEDIUM] Field 'email' contains high null percentage (20.0%).
- [MEDIUM] Unresolved FK candidate(s): ['parent_ref']
- [MEDIUM] Field 'closed_date' contains high null percentage (55.0%).
- [MEDIUM] Unresolved FK candidate(s): ['equip_id', 'technician_ref']

### Wave 2 — Assets
**CSV Files:** D:\Hackathon\Onboardiq-merged\Onboardiq-merged\workspaces\users\user1\outputs\silver\wave_02\assets.csv
**Tool Stack:** Pandas
**Wave Rows:** 10

This wave focuses on migrating Assets, which are critical for tracking equipment and maintenance history. It's separated from Wave 1 due to the complexity of resolving FK constraints and data quality issues specific to asset records.

**Approach:** A full load to CSV is recommended, preceded by a lookup-first approach to validate and correct FK references to Locations before loading.

**Risk Mitigations:**
- Investigate and correct the orphan records in Assets by either updating the FK values or archiving the records if they are invalid.
- Populate the 'loc_code' field in Assets by matching against the Locations table, using a defined mapping or business rule.
- Define a default 'status' value for Assets with missing status information, ensuring consistency and usability.

**Risks (4):**
- [MEDIUM] 1 orphan record(s) (broken FK references)
- [MEDIUM] Field 'loc_code' contains high null percentage (20.0%).
- [MEDIUM] Field 'status' contains high null percentage (10.0%).
- [MEDIUM] Referential integrity check failed: 1 orphan records reference invalid 'Locations.location_key' values.
