# Tax proof arguments for rejected proposals

Pass 4, base `d6ed66bc`. The owner approved only the six IDs in
`config/tax-equivalent-mutants.json`. All 27 IDs below remain **unlisted**;
their survival still fails both their job and the final aggregate.

The executable obligations are in
`backend/tests/test_tax_equivalence_proofs.py`, one parametrized case per ID.
They regenerate authentic pinned mutmut 3.8.0 bodies in memory and check that
each individual change satisfies its stated premise. They are deliberately
outside the unchanged tax test selector: syntax checks cannot be counted as
behavior kills. The supporting public tests are in the already selected
`test_tax_guards.py`: exact Decimal zeros/scales, unwashed sales, all 16 rate
availability combinations, Unicode bytes and immutable account paths.

Local direct-body replay of all 27 rejected IDs passes those 23 public tests
(plus a pristine baseline). This is corroboration, not an exhaustive history
search or a native Linux mutation certificate. Native CI remains authoritative.

The all-input arguments depend on the validated public input domain and the
pinned Python/Pydantic implementations, without monkeypatches or forged model
instances. Inputs rejected before the mutation have the same rejection.

## Complete abstractions and induction premises

- **rank**: BUY and SELL are the entire validated enum. Multiplying their two
  ranks by two is a strict order isomorphism. Timestamp and UUID components
  are unchanged. The test exhausts both sides and all three comparison
  outcomes for the other two components, covering every lexicographic case.
- **present**: `_survivors` builds ordinary dictionaries. The enclosing `in`
  condition dominates the sole `get` expression; nothing writes between them.
  For every present key and arbitrary value, built-in `get` returns that same
  object regardless of default. Absent keys cannot reach the changed call.
- **zip**: `False`, `None`, and the omitted default select the identical false
  strictness state. The test compares the built-in iterator's complete reduce
  state with the very same arbitrary iterator objects. Each next transition,
  including termination/errors, is therefore identical by induction.
- **positive**: sorted distinct boundary sets make positive-width parts.
  A disposal advances by at most that width; exhausted parts are removed.
  Induction over fills preserves positive width for every selected part.
  All weak orderings of the four interval endpoints have a representative
  among ranks 0..3; the test exhausts them under this invariant.
- **fresh**: assignments are chronological complements of all earlier assigned
  physical-share intervals. For each allocator step, a positive emitted gap
  ends at or before the next occupied start, and the cursor then advances to
  at least its end. Induction over sorted intervals proves disjointness;
  extending `assigned` proves disjointness across losses. Refinement includes
  every allocation endpoint before replay, so each selected part consists
  entirely of shares assigned once. Parts start with zero extra basis. Splits
  and disposals do not create physical shares or remove their assignment.
  Thus the old extra is zero at its sole assignment. The test binds these
  source premises and symbolically evaluates the authentic arithmetic as
  affine coefficients in arbitrary `next_amount` and `allocated` integers:
  `0 + (a-b)` and `a-b` have identical coefficients. No magnitude bound or
  sampled maximum is used in the algebraic step.
- **sum**: empty and nonempty are the complete sequence cases. Empty int 0
  and Decimal(0) normalize to the same public Money representation. For a
  nonempty sequence of validated Decimals, integer-zero addition converts
  its integer operand exactly to Decimal(0), giving the identical first
  Decimal operation (including rounding/sign/flags); induction makes every
  later operation identical. TaxSale revalidation and AnnualTax construction
  normalize empty direct totals; all intervening arithmetic has a Decimal
  operand. The operator checks include signed/exponent zeros, precision
  extremes and scaled-money limits. Public tests check types and tuples,
  including the cent exponent of the set-aside estimate.
- **codec**: both spellings resolve to the identical codec object and encoder
  callable, not merely equal outputs for ASCII samples. The function is
  identical for every string, including any encoding error. The source
  operands are built-in joined/formatted strings, not custom encoders.
- **mode**: AnnualTax's closed schema has only int, str, bool, finite Decimal,
  None, and a tuple of strings; neither it nor its fields has serialization
  callbacks. Its pinned primitive serializers use the non-JSON branch for
  these four modes. Values are returned in their Python forms, with Decimal
  precision/sign/exponent unchanged. The test checks the complete schema
  kinds and absence of serialization overrides, then type/object identity
  for primitive output cells across modes. A different serializer or schema
  invalidates these premises; this is not a claim about arbitrary models.
- **precision**: nonempty `min` ignores either default for every exponent.
  Empty `min` yields the only two values 0 and 1, and the preceding precision
  80 dominates both 32 and 31. The precision setting is therefore identical
  for all rate inputs, including all four unavailable.

## Individual obligations

| Mutant ID (unlisted) | Proof | Why the reachable output is unchanged |
| --- | --- | --- |
| `backend.tax.lots.xǁWashSaleMatcherǁ_inputs__mutmut_29` | rank | For every validated BUY/SELL, tags (0,1) and (0,2) impose the identical timestamp/side/UUID total order. |
| `backend.tax.lots.xǁWashSaleMatcherǁallocations__mutmut_44` | present | The preceding membership test guarantees the replacement ID exists; the changed dict.get default is never used. |
| `backend.tax.lots.xǁWashSaleMatcherǁallocations__mutmut_46` | present | The preceding membership test guarantees the replacement ID exists; omitting the dict.get default cannot change a matched quantity. |
| `backend.tax.lots.xǁWashSaleMatcherǁallocations__mutmut_47` | present | The preceding membership test guarantees the replacement ID exists; changing its unused default to 1 cannot change a matched quantity. |
| `backend.tax.accounting.x__rebuild__mutmut_107` | zip | zip(strict=None) and zip(strict=False) both disable strict length checking; the same adjacent share boundaries are paired. |
| `backend.tax.accounting.x__rebuild__mutmut_110` | zip | Omitting zip(strict=False) selects the same False default and produces the same adjacent share intervals. |
| `backend.tax.accounting.x__rebuild__mutmut_35` | positive | Distinct sorted share boundaries create only positive-width parts, and exhausted parts are removed before apply; start == end cannot be selected. |
| `backend.tax.accounting.x__rebuild__mutmut_53` | fresh | The sole caller supplies matcher allocations that assign every physical replacement share once; each selected part therefore has extra == 0 before its only addition. |
| `backend.tax.accounting.x_build_tax_book__mutmut_114` | sum | Removing the Decimal zero start leaves nonempty Decimal sums unchanged; the empty integer zero is normalized by TaxSale money validation. |
| `backend.tax.accounting.x_build_tax_book__mutmut_123` | sum | Removing the Decimal zero start leaves permanent-loss sums unchanged; TaxSale converts the empty integer zero to the same Decimal zero. |
| `backend.tax.accounting.x_build_tax_book__mutmut_134` | sum | Economic gain plus an empty integer zero equals gain plus Decimal zero; nonempty disallowed-loss sums remain Decimal. |
| `backend.tax.accounting.x_build_tax_book__mutmut_32` | rank | For all validated fill sides, replacing SELL tag 1 with 2 preserves the complete timestamp/BUY-before-SELL/UUID order. |
| `backend.tax.reports.x_annual__mutmut_119` | sum | A missing LT sum starts at integer zero instead of Decimal zero; later money validation normalizes it, and nonempty Decimal sums are unchanged. |
| `backend.tax.reports.x_annual__mutmut_190` | sum | Empty dividend integer zero is normalized by AnnualTax money validation; nonempty dividend sums remain Decimal. |
| `backend.tax.reports.x_annual__mutmut_200` | sum | Empty interest integer zero is normalized by AnnualTax money validation; nonempty interest sums remain Decimal. |
| `backend.tax.reports.x_annual__mutmut_210` | sum | Empty fee integer zero is normalized by AnnualTax money validation; nonempty absolute fee sums remain Decimal. |
| `backend.tax.reports.x_annual__mutmut_226` | sum | Adding an empty integer-zero dividend sum to Decimal interest gives the same ordinary-income amount. |
| `backend.tax.reports.x_annual__mutmut_242` | sum | An empty qualified-income integer zero is used in the same Decimal arithmetic and final cent quantization. |
| `backend.tax.reports.x_annual__mutmut_340` | sum | Empty wash-disallowed integer zero is normalized by AnnualTax money validation; nonempty wash sums remain Decimal. |
| `backend.tax.reports.x_annual__mutmut_346` | sum | Empty permanent-loss integer zero is normalized by AnnualTax money validation; nonempty permanent-loss sums remain Decimal. |
| `backend.tax.reports.x_annual__mutmut_109` | sum | A missing ST sum starts at integer zero instead of Decimal zero; later money validation normalizes it, and nonempty Decimal sums are unchanged. |
| `backend.tax.reports.x_render_report__mutmut_195` | codec | README UTF-8 and utf-8 encoding use the same Python codec and produce identical bytes. |
| `backend.tax.reports.x_render_report__mutmut_91` | mode | AnnualTax includes only built-in int/str/bool/finite Decimal/None cells and has no custom serializers; pinned Pydantic treats mode=None as the same non-JSON Python-value branch. |
| `backend.tax.reports.x_render_report__mutmut_92` | mode | AnnualTax includes only built-in int/str/bool/finite Decimal/None cells and has no custom serializers; pinned Pydantic treats mode=XXpythonXX as the same non-JSON Python-value branch. |
| `backend.tax.reports.x_render_report__mutmut_93` | mode | AnnualTax includes only built-in int/str/bool/finite Decimal/None cells and has no custom serializers; pinned Pydantic treats mode=PYTHON as the same non-JSON Python-value branch. |
| `backend.tax.reports.x_save_report__mutmut_44` | codec | UTF-8 and utf-8 encode account names identically, so the account-bound directory hash is unchanged. |
| `backend.tax.reports.x_annual__mutmut_104` | precision | The changed min default is reached only with four unavailable rates; max(80,32) == max(80,31), so all arithmetic and the unavailable estimate are identical. |

No new production bug or source change is claimed. These tests and arguments
do not authorize another equivalent entry. If an all-input premise is disputed,
the ID remains a failing unlisted survivor until a behavior counterexample or
an owner decision resolves it.
