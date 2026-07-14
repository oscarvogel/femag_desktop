# Design QA - issue #178 pallet workflow

- Source visual truth: `C:\Users\OSCAR24\.codex\generated_images\019f6253-33ae-7421-ad68-a15261b0d169\exec-fd6bb544-d09b-4b43-a533-d23b3fdfd2ac.png`
- Implementation screenshot: `docs/screenshots/issue_178_pallet_composition/02_panel_lateral_pallet_mixto.png`
- Empty-state screenshot: `docs/screenshots/issue_178_pallet_composition/01_nueva_orden_grilla_pallets.png`
- Viewport: source 1440x1024; implementation 1440x900 desktop window.
- State: saved pending order with no pallets and the contextual `Armar pallets` action.

## Full-view comparison evidence

The implementation preserves the selected concept's information hierarchy: the order exists first, pallet preparation has its own status column, and `Armar pallets` is an action on the corresponding row. Existing operational actions remain in the page toolbar so emission, printing, budget and annulment are not regressed.

## Focused region comparison evidence

The order row was checked at full resolution. `Sin preparar`, `Pendiente`, and `Armar pallets` are readable without clipping. The transport detail remains available in the expanded detail row rather than competing with pallet preparation in the main row.

## Findings

- No P0/P1/P2 findings remain.
- P3: the native PyQt table is visually denser and does not reproduce the mock's progress bars. This is acceptable for this iteration because it preserves the established FEMAG desktop components and shows equivalent explicit progress text.
- P3: the existing global toolbar is retained instead of moving every order operation into the row. This intentionally avoids changing unrelated operational behavior.

## Comparison history

1. Initial implementation kept driver, carrier and truck as main table columns and placed `Armar pallets` in the toolbar. This drifted from the selected concept and made the table crowded.
2. The main row was reduced to order, customer/destination/product, pallet preparation, state and contextual action. Transport information remains in the existing expanded detail. The post-fix screenshot is the implementation evidence listed above.
3. Manual review rejected the initial pallet dialog because it exposed enabled editor actions before a pallet existed and rendered the total with poor contrast. The empty state now shows pending units centrally, uses `Agregar primer pallet`, disables the editor and save action, starts quantity at 1, and gives the total explicit high-contrast colors. The post-fix evidence is the empty-state screenshot listed above.

## Verification limits

The automated capture verifies the visible desktop state. Keyboard focus order and high-DPI scaling still require a manual workstation check.

final result: passed
