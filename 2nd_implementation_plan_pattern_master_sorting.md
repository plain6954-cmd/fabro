# Implementation Plan: Pattern Master Column Sorting (Brand, Model, Vehicle Country, Measurement Country)

This document specifies the technical design and implementation steps for making the **Brand**, **Model**, **Vehicle Country**, and **Measurement Country** column headers in **Pattern Master** (`/car-details/`) act as seamless, invisible buttons that toggle between ascending (A → Z) and descending (Z → A) alphabetical order.

---

## 1. Requirements & User Experience Design

### 1.1 Target Columns
From the green highlighted area in the Pattern Master table header:
1. **Brand** (`col-brand`, column index 2)
2. **Model** (`col-model`, column index 3)
3. **Vehicle Country** (`col-country col-vehicle-country`, column index 10)
4. **Measurement Country** (`col-country col-measurement-country`, column index 11)

### 1.2 "Invisible Button" Interaction Behavior
- **Seamless Appearance:** The column title area will act as a button without looking like a bulky/raised button. It retains the dark glassmorphic table header styling with:
  - `cursor: pointer`
  - Flat transparent styling (`background: none; border: none; padding: 0; color: inherit; font: inherit;`)
  - Subtle hover highlight (text turns brighter white / slight red tint)
  - Accessible button attributes (`role="button"`, `tabindex="0"`, `aria-label="Sort by..."`, `aria-sort="none|ascending|descending"`)
- **Sort State Indicator:** A subtle sort arrow icon will be placed beside the text:
  - Idle state: faint neutral sort glyph (`fa-sort` at low opacity, or hidden until hover)
  - Ascending state: active indicator (`fa-arrow-up-a-z` or `fa-sort-up` in `var(--primary-color)`)
  - Descending state: active indicator (`fa-arrow-down-z-a` or `fa-sort-down` in `var(--primary-color)`)
- **Toggle Sequence:**
  - **1st Click:** Sorts rows in **Ascending** alphabetical order (A → Z).
  - **2nd Click:** Sorts rows in **Descending** alphabetical order (Z → A).
  - **3rd Click:** Resets back to the **default serial number based order** and resets the sort arrow icon to idle.
  - Sorting on any column resets the active sort state of other columns.

### 1.3 Collision Prevention with Filter Triggers
- In Pattern Master, each column header already contains:
  - `.column-filter-trigger` (the chevron dropdown icon)
  - `.column-filter-clear` (the "x" clear filter button)
  - `.tooltip-container` (the info icon on Vehicle Country & Measurement Country)
- **Strict Event Isolation:** Clicks on `.column-filter-trigger`, `.column-filter-clear`, and `.tooltip-container` call `e.stopPropagation()` so opening the filter dropdown or viewing a tooltip **never** triggers sorting.
- Sorting only triggers when the user clicks the column header text / title area.

---

## 2. Technical Implementation Architecture

### 2.1 Preserving Paired Table Rows
In Pattern Master, vehicles in `<tbody>` consist of pairs of table rows:
- View Row: `<tr id="row-view-{{ car.id }}" data-car-id="{{ car.id }}">`
- Edit Row (when staff): `<tr id="row-edit-{{ car.id }}" class="inline-edit-row" data-car-id="{{ car.id }}">`
- Inline Add Row: `<tr id="inline-add-row">` (always stays anchored at the top)

**Critical Sorting Rule:** When reordering rows in the DOM, the view row and its corresponding inline-edit row must move together as an atomic unit so that clicking "Edit" opens the edit form directly beneath the correct vehicle.

### 2.2 Text Extraction & Natural Sorting
- For **Brand**: Extract cleaned text from `td.col-brand` (e.g. "CHEVROLET", "FORD").
- For **Model**: Extract cleaned text from `td.col-model` (e.g. "CAPTIVA", "EVEREST").
- For **Vehicle Country**: Extract cleaned text from `td.col-vehicle-country` (ignoring `-` or empty values).
- For **Measurement Country**: Extract cleaned text from `td.col-measurement-country` (ignoring `-` or empty values).
- **Empty / Dash Handling:** Values with `-` or empty strings are treated as trailing values (placed at the bottom in ascending order).
- **Comparison Engine:** Uses JavaScript `Intl.Collator` or `String.prototype.localeCompare(..., { sensitivity: 'base', numeric: true })` for proper natural language sorting.

### 2.3 Compatibility with Active Column Filters
- When sorting is applied, currently filtered/hidden rows remain hidden.
- The sort operates across all rows in the current table dataset and appends them in sorted order.

---

## 3. Proposed Code Modifications

### 3.1 Template Changes: [car_details.html](file:///c:/Users/POWER-13/Documents/FABRO/Fabro-Leather-Portal/management/templates/management/car_details.html)

1. **Wrap Column Titles in Sort Buttons:**
   - In `<th class="col-brand">`:
     ```html
     <button type="button" class="col-sort-btn" data-sort-key="brand" title="{% translate "Sort by Brand" %}">
         <span>{% translate "Brand" %}</span>
         <i class="fas fa-sort col-sort-icon"></i>
     </button>
     ```
   - In `<th class="col-model">`:
     ```html
     <button type="button" class="col-sort-btn" data-sort-key="model" title="{% translate "Sort by Model" %}">
         <span>{% translate "Model" %}</span>
         <i class="fas fa-sort col-sort-icon"></i>
     </button>
     ```
   - In `<th class="col-vehicle-country">`:
     ```html
     <button type="button" class="col-sort-btn" data-sort-key="vehicle_country" title="{% translate "Sort by Vehicle Country" %}">
         <span>{% translate "Vehicle Country" %}</span>
         <i class="fas fa-sort col-sort-icon"></i>
     </button>
     ```
   - In `<th class="col-measurement-country">`:
     ```html
     <button type="button" class="col-sort-btn" data-sort-key="measurement_country" title="{% translate "Sort by Measurement Country" %}">
         <span>{% translate "Measurement Country" %}</span>
         <i class="fas fa-sort col-sort-icon"></i>
     </button>
     ```

2. **Add Sort Styles to Pattern Master CSS:**
   ```css
   .col-sort-btn {
       background: transparent;
       border: none;
       padding: 0;
       margin: 0;
       color: inherit;
       font: inherit;
       font-weight: 600;
       font-size: 0.8rem;
       cursor: pointer;
       display: inline-flex;
       align-items: center;
       gap: 0.35rem;
       transition: color 0.15s ease;
       text-align: left;
       user-select: none;
   }
   .col-sort-btn:hover {
       color: #ffffff;
   }
   .col-sort-icon {
       font-size: 0.65rem;
       opacity: 0.35;
       transition: opacity 0.15s ease, transform 0.15s ease, color 0.15s ease;
   }
   .col-sort-btn:hover .col-sort-icon {
       opacity: 0.75;
   }
   .col-sort-btn.is-sorted .col-sort-icon {
       opacity: 1;
       color: var(--primary-color);
   }
   ```

3. **Add Table Sorting Controller in JavaScript:**
   ```javascript
   let currentSortKey = null;
   let currentSortDir = 'none'; // 'asc' | 'desc'

   function sortPatternTable(sortKey) {
       const tbody = document.querySelector('.table tbody');
       if (!tbody) return;

       // Determine next direction
       if (currentSortKey === sortKey) {
           currentSortDir = (currentSortDir === 'asc') ? 'desc' : 'asc';
       } else {
           currentSortKey = sortKey;
           currentSortDir = 'asc';
       }

       // Update UI button icons & aria attributes
       document.querySelectorAll('.col-sort-btn').forEach(btn => {
           const icon = btn.querySelector('.col-sort-icon');
           if (btn.dataset.sortKey === sortKey) {
               btn.classList.add('is-sorted');
               btn.setAttribute('aria-sort', currentSortDir === 'asc' ? 'ascending' : 'descending');
               if (icon) {
                   icon.className = currentSortDir === 'asc' ? 'fas fa-arrow-up-a-z col-sort-icon' : 'fas fa-arrow-down-z-a col-sort-icon';
               }
           } else {
               btn.classList.remove('is-sorted');
               btn.setAttribute('aria-sort', 'none');
               if (icon) icon.className = 'fas fa-sort col-sort-icon';
           }
       });

       // Gather row pairs
       const viewRows = Array.from(tbody.querySelectorAll('tr[id^="row-view-"]'));
       const rowPairs = viewRows.map(viewRow => {
           const carId = viewRow.getAttribute('data-car-id');
           const editRow = document.getElementById(`row-edit-${carId}`);
           let cellValue = '';
           if (sortKey === 'brand') {
               cellValue = viewRow.querySelector('.col-brand')?.textContent?.trim() || '';
           } else if (sortKey === 'model') {
               cellValue = viewRow.querySelector('.col-model')?.textContent?.trim() || '';
           } else if (sortKey === 'vehicle_country') {
               cellValue = viewRow.querySelector('.col-vehicle-country')?.textContent?.trim() || '';
           } else if (sortKey === 'measurement_country') {
               cellValue = viewRow.querySelector('.col-measurement-country')?.textContent?.trim() || '';
           }
           return { viewRow, editRow, value: cellValue };
       });

       // Sort pairs alphabetically
       const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });
       rowPairs.sort((a, b) => {
           const valA = (a.value === '-' ? '' : a.value);
           const valB = (b.value === '-' ? '' : b.value);
           if (!valA && valB) return 1;
           if (valA && !valB) return -1;
           const cmp = collator.compare(valA, valB);
           return currentSortDir === 'asc' ? cmp : -cmp;
       });

       // Re-append sorted pairs in tbody (preserving inline-add row at top)
       const addRow = document.getElementById('inline-add-row');
       if (addRow) tbody.appendChild(addRow);

       rowPairs.forEach(pair => {
           tbody.appendChild(pair.viewRow);
           if (pair.editRow) tbody.appendChild(pair.editRow);
       });
   }
   ```

---

## 4. Verification Plan

### Automated Tests
- Add unit/integration test in `management/tests.py`:
  - Verify table headers render with sorting buttons and proper accessibility attributes.
  - Verify sort buttons do not interfere with column filter modal elements.

### Manual Verification
1. **Brand Column:**
   - Click "Brand" once: verify rows rearrange from A to Z (e.g. CHEVROLET → DODGE → FORD).
   - Click "Brand" a second time: verify rows rearrange from Z to A (e.g. FORD → DODGE → CHEVROLET).
2. **Model Column:**
   - Click "Model": verify models sort alphabetically (A → Z), and second click sorts (Z → A).
3. **Vehicle Country & Measurement Country:**
   - Click "Vehicle Country": verify countries sort alphabetically, with empty/dash values positioned cleanly at the end.
   - Click "Measurement Country": verify same behavior.
4. **Non-interference Test:**
   - Click the chevron filter trigger: verify filter dropdown opens without triggering sort.
   - Click an active sort column while a filter is applied: verify filtered visible items reorder correctly.
   - Open Inline Edit on a sorted row: verify the edit row opens directly beneath the vehicle and saves normally.
