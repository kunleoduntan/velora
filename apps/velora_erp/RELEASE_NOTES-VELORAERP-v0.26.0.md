# VeloraERP 0.26.0

**Framework compatibility:** Velora >=0.85.1,<0.86  
**Release focus:** Fixed Asset Depreciation and Impairment

## Delivered

- Fixed Asset Depreciation Run and child line DocTypes.
- Straight Line, Reducing Balance and Units of Production depreciation calculations.
- Prospective straight-line depreciation after revaluation and impairment.
- Period-overlap protection, asset/company checks, account and dimension validation.
- Central-ledger depreciation posting with subledger updates after successful posting.
- Fixed Asset Impairment for impairment losses and controlled reversals.
- Carrying amount ceiling tracking for impairment reversals, reduced by hypothetical depreciation.
- Category defaults and acquisition-time depreciation inputs for Fixed Asset Purchase and Purchase Invoice.
- ROU assets from Fixed Asset Lease participate in depreciation runs.
- Fixed Asset workspace shortcuts for Depreciation Runs and Asset Impairment.
- Migration patch `v0_24.extend_fixed_asset_workspace`.

## Not included

Depreciation books, component accounting, automatic run generation, auto-posting, CGU impairment, lease modification/termination and lessor accounting remain future work.
