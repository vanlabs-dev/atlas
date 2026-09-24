## REMOVED Requirements

### Requirement: Root-rotation is a delivered class rendered from recorded fields

**Reason**: Spec 469 retired root weight vectors, so no root-rotation event
can be produced. The class was at the shadow tier and never sent.

**Migration**: None. The class is removed from configuration and the scan.
Its watermark and ledger rows stay in the store unchanged.
