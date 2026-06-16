# Onboarding Plan

**Migration Readiness Score:** 71.9/100

**Silver Waves:** 2


## Bronze-Silver-Gold Pipeline

### Bronze
Raw ingest layer — all source entities are captured as-is with no wave sequencing.
**Entities:** Assets, Locations, WorkOrders, Users
**Raw Ingest Items:**
- Assets (RAW)
- Locations (RAW)
- WorkOrders (RAW)
- Users (RAW)

### Silver
Wave-sequenced transformation layer — entities are processed into CSV files in dependency order.
#### Wave 1
**Entities:** Assets, Locations, Users
**CSV Files:** D:\Hackathon\Onboardiq-merged\Onboardiq-merged\outputs\silver\wave_01\assets.csv, D:\Hackathon\Onboardiq-merged\Onboardiq-merged\outputs\silver\wave_01\locations.csv, D:\Hackathon\Onboardiq-merged\Onboardiq-merged\outputs\silver\wave_01\users.csv
**Tool Stack:** Pandas
**Wave Rows:** 19
This wave focuses on foundational entities – Assets, Locations, and Users – establishing the core data structure for the system. These entities are grouped together as they represent the fundamental building blocks for tracking resources and personnel.
**Approach:** A full load to CSV is recommended, prioritizing data cleansing and validation to address the identified null percentages and foreign key issues before loading into the target system.
**Risk Mitigations:**
- Implement a data quality rule to populate 'status' in Assets with a default value if null, based on business logic.
- Develop a lookup table to map 'loc_code' in Assets to valid Location IDs, handling the 20% null rate by assigning a default location or flagging for manual review.
- Investigate and resolve the 'parent_ref' foreign key issue in Locations by identifying the correct parent records or creating placeholder records if necessary.
**Risks (5):**
- [MEDIUM] Field 'loc_code' contains high null percentage (20.0%).
- [MEDIUM] Field 'status' contains high null percentage (10.0%).
- [MEDIUM] Unresolved FK candidate(s): ['loc_code']
- [MEDIUM] Unresolved FK candidate(s): ['parent_ref']
- [MEDIUM] Field 'email' contains high null percentage (20.0%).
#### Wave 2
**Entities:** WorkOrders
**CSV Files:** D:\Hackathon\Onboardiq-merged\Onboardiq-merged\outputs\silver\wave_02\workorders.csv
**Tool Stack:** Pandas
**Wave Rows:** 20
This wave migrates WorkOrders, which depend on the entities loaded in Wave 1, and represents a key business process. It's crucial to ensure data integrity, particularly regarding foreign key relationships and required fields.
**Approach:** A lookup-first approach is recommended, validating 'assigned_user', 'technician_ref', and 'asset_no' against the data loaded in Wave 1 before loading WorkOrders to ensure referential integrity.
**Risk Mitigations:**
- Map the 'assigned_user' field to the Users table and implement a default user assignment process for any missing values.
- Investigate the orphan WorkOrder records and either update them with valid foreign key values or archive them after business review.
- Analyze the 'closed_date' nulls and determine if a default closed date or a separate process for handling incomplete work orders is required.
**Risks (5):**
- [CRITICAL] 1 required target field(s) unmapped: ['assigned_user']
- [MEDIUM] 1 orphan record(s) (broken FK references)
- [MEDIUM] Field 'closed_date' contains high null percentage (55.0%).
- [MEDIUM] Referential integrity check failed: 1 orphan records reference invalid 'Assets.asset_no' values.
- [MEDIUM] Unresolved FK candidate(s): ['technician_ref']

### Gold
Target load layer — Silver CSV outputs are loaded into the target database.
#### Load Wave 1
**Source CSVs:** D:\Hackathon\Onboardiq-merged\Onboardiq-merged\outputs\silver\wave_01\assets.csv, D:\Hackathon\Onboardiq-merged\Onboardiq-merged\outputs\silver\wave_01\locations.csv, D:\Hackathon\Onboardiq-merged\Onboardiq-merged\outputs\silver\wave_01\users.csv
**Target Entities:** Assets, Locations, Users
**Target:** target_db
**Strategy:** bulk load from Silver CSVs
#### Load Wave 2
**Source CSVs:** D:\Hackathon\Onboardiq-merged\Onboardiq-merged\outputs\silver\wave_02\workorders.csv
**Target Entities:** WorkOrders
**Target:** target_db
**Strategy:** bulk load from Silver CSVs

## Silver Wave Detail

### Wave 1 — Assets, Locations, Users
**CSV Files:** D:\Hackathon\Onboardiq-merged\Onboardiq-merged\outputs\silver\wave_01\assets.csv, D:\Hackathon\Onboardiq-merged\Onboardiq-merged\outputs\silver\wave_01\locations.csv, D:\Hackathon\Onboardiq-merged\Onboardiq-merged\outputs\silver\wave_01\users.csv
**Tool Stack:** Pandas
**Wave Rows:** 19

This wave focuses on foundational entities – Assets, Locations, and Users – establishing the core data structure for the system. These entities are grouped together as they represent the fundamental building blocks for tracking resources and personnel.

**Approach:** A full load to CSV is recommended, prioritizing data cleansing and validation to address the identified null percentages and foreign key issues before loading into the target system.

**Risk Mitigations:**
- Implement a data quality rule to populate 'status' in Assets with a default value if null, based on business logic.
- Develop a lookup table to map 'loc_code' in Assets to valid Location IDs, handling the 20% null rate by assigning a default location or flagging for manual review.
- Investigate and resolve the 'parent_ref' foreign key issue in Locations by identifying the correct parent records or creating placeholder records if necessary.

**Risks (5):**
- [MEDIUM] Field 'loc_code' contains high null percentage (20.0%).
- [MEDIUM] Field 'status' contains high null percentage (10.0%).
- [MEDIUM] Unresolved FK candidate(s): ['loc_code']
- [MEDIUM] Unresolved FK candidate(s): ['parent_ref']
- [MEDIUM] Field 'email' contains high null percentage (20.0%).

### Wave 2 — WorkOrders
**CSV Files:** D:\Hackathon\Onboardiq-merged\Onboardiq-merged\outputs\silver\wave_02\workorders.csv
**Tool Stack:** Pandas
**Wave Rows:** 20

This wave migrates WorkOrders, which depend on the entities loaded in Wave 1, and represents a key business process. It's crucial to ensure data integrity, particularly regarding foreign key relationships and required fields.

**Approach:** A lookup-first approach is recommended, validating 'assigned_user', 'technician_ref', and 'asset_no' against the data loaded in Wave 1 before loading WorkOrders to ensure referential integrity.

**Risk Mitigations:**
- Map the 'assigned_user' field to the Users table and implement a default user assignment process for any missing values.
- Investigate the orphan WorkOrder records and either update them with valid foreign key values or archive them after business review.
- Analyze the 'closed_date' nulls and determine if a default closed date or a separate process for handling incomplete work orders is required.

**Risks (5):**
- [CRITICAL] 1 required target field(s) unmapped: ['assigned_user']
- [MEDIUM] 1 orphan record(s) (broken FK references)
- [MEDIUM] Field 'closed_date' contains high null percentage (55.0%).
- [MEDIUM] Referential integrity check failed: 1 orphan records reference invalid 'Assets.asset_no' values.
- [MEDIUM] Unresolved FK candidate(s): ['technician_ref']
