document.addEventListener("DOMContentLoaded", () => {
    const ignoredHeaders = new Set(["actions", "action", "details", "timestamp", "created", "id", "password"]);

    function normalize(value) {
        return (value || "").toString().toLowerCase().trim();
    }

    function parseComparable(value) {
        const normalized = normalize(value);
        if (!normalized) {
            return { type: "text", value: "" };
        }

        const numeric = Number(normalized.replace(/[^0-9.-]/g, ""));
        if (!Number.isNaN(numeric) && normalized.replace(/[^0-9.-]/g, "") !== "") {
            return { type: "number", value: numeric };
        }

        const dateValue = Date.parse(value);
        if (!Number.isNaN(dateValue)) {
            return { type: "date", value: dateValue };
        }

        return { type: "text", value: normalized };
    }

    function compareRows(leftRow, rightRow, columnIndex, direction) {
        const leftCell = leftRow.cells[columnIndex];
        const rightCell = rightRow.cells[columnIndex];
        const leftValue = leftCell ? leftCell.textContent : "";
        const rightValue = rightCell ? rightCell.textContent : "";
        const leftComparable = parseComparable(leftValue);
        const rightComparable = parseComparable(rightValue);
        const multiplier = direction === "desc" ? -1 : 1;

        if (leftComparable.type === "number" && rightComparable.type === "number") {
            return (leftComparable.value - rightComparable.value) * multiplier;
        }

        if (leftComparable.type === "date" && rightComparable.type === "date") {
            return (leftComparable.value - rightComparable.value) * multiplier;
        }

        return leftComparable.value.toString().localeCompare(rightComparable.value.toString()) * multiplier;
    }

    function buildToolbar(table, columns, state) {
        const toolbar = document.createElement("div");
        toolbar.className = "d-flex flex-wrap align-items-end mb-3";
        toolbar.style.gap = "0.75rem";

        const searchGroup = document.createElement("div");
        searchGroup.style.flex = "1 1 280px";
        const searchInput = document.createElement("input");
        searchInput.type = "search";
        searchInput.className = "form-control";
        searchInput.placeholder = state.searchPlaceholder || "Search table...";
        searchGroup.appendChild(searchInput);

        const filterGroups = [];
        state.filters.forEach((filterInfo) => {
            const group = document.createElement("div");
            group.style.flex = "0 1 220px";
            const select = document.createElement("select");
            select.className = "custom-select";

            const allOption = document.createElement("option");
            allOption.value = "all";
            allOption.textContent = `All ${filterInfo.label}`;
            select.appendChild(allOption);

            filterInfo.values.forEach((value) => {
                const option = document.createElement("option");
                option.value = value;
                option.textContent = value;
                select.appendChild(option);
            });

            filterInfo.select = select;
            group.appendChild(select);
            filterGroups.push(group);
        });

        const actionsGroup = document.createElement("div");
        actionsGroup.style.flex = "0 0 auto";
        const clearButton = document.createElement("button");
        clearButton.type = "button";
        clearButton.className = "btn btn-outline-secondary";
        clearButton.innerHTML = '<i class="fas fa-eraser mr-1"></i> Clear';
        actionsGroup.appendChild(clearButton);

        const summary = document.createElement("small");
        summary.className = "text-muted d-block w-100";
        summary.style.marginTop = "0.25rem";

        toolbar.appendChild(searchGroup);
        filterGroups.forEach((group) => toolbar.appendChild(group));
        toolbar.appendChild(actionsGroup);
        toolbar.appendChild(summary);

        table.parentElement.insertBefore(toolbar, table);

        return { searchInput, clearButton, summary };
    }

    function enhanceTable(table) {
        if (!table.tHead || !table.tBodies.length) {
            return;
        }

        const headers = Array.from(table.tHead.rows[0].cells).map((cell, index) => ({
            index,
            label: normalize(cell.textContent),
            cell,
        }));
        const rows = Array.from(table.tBodies[0].rows).filter((row) => row.cells.length > 0 && !row.dataset.tableEmpty);
        if (!rows.length) {
            return;
        }

        const tableTitle = table.dataset.tableTitle || "table";
        const state = {
            searchPlaceholder: `Search ${tableTitle}...`,
            filters: [],
            sortIndex: 0,
            sortDirection: "asc",
            searchValue: "",
        };

        headers.forEach((header) => {
            if (ignoredHeaders.has(header.label)) {
                return;
            }

            const uniqueValues = Array.from(new Set(rows.map((row) => normalize(row.cells[header.index]?.textContent)).filter(Boolean)));
            if (uniqueValues.length >= 2 && uniqueValues.length <= 10 && uniqueValues.every((value) => value.length <= 40)) {
                state.filters.push({ index: header.index, label: header.cell.textContent.trim(), values: uniqueValues.sort() });
            }
        });

        const toolbar = buildToolbar(table, headers, state);

        function render() {
            const searchTerm = normalize(toolbar.searchInput.value);
            const activeFilters = state.filters
                .map((filterInfo) => ({ index: filterInfo.index, value: normalize(filterInfo.select.value) }))
                .filter((filter) => filter.value && filter.value !== "all");

            const visibleRows = rows.filter((row) => {
                const rowText = normalize(row.textContent);
                const matchesSearch = !searchTerm || rowText.includes(searchTerm);
                const matchesFilters = activeFilters.every((filter) => normalize(row.cells[filter.index]?.textContent) === filter.value);
                return matchesSearch && matchesFilters;
            });

            const sortedRows = visibleRows.slice().sort((left, right) => compareRows(left, right, state.sortIndex, state.sortDirection));

            rows.forEach((row) => {
                row.style.display = "none";
            });

            sortedRows.forEach((row) => {
                row.style.display = "";
                table.tBodies[0].appendChild(row);
            });

            toolbar.summary.textContent = `${sortedRows.length} of ${rows.length} rows visible`;
        }

        function resolveColumnIndex(reference) {
            if (reference === undefined || reference === null || reference === "") {
                return 0;
            }

            const numericIndex = Number(reference);
            if (!Number.isNaN(numericIndex)) {
                return Math.max(0, Math.min(headers.length - 1, numericIndex));
            }

            const normalizedReference = normalize(reference);
            const foundHeader = headers.find((header) => header.label === normalizedReference || normalize(header.cell.textContent) === normalizedReference);
            return foundHeader ? foundHeader.index : 0;
        }

        function applyShortcut(shortcutElement) {
            const searchValue = shortcutElement.dataset.tableSearch;
            const filterColumn = shortcutElement.dataset.tableFilterColumn;
            const filterValue = shortcutElement.dataset.tableFilterValue;
            const sortColumn = shortcutElement.dataset.tableSortColumn;
            const sortDirectionValue = shortcutElement.dataset.tableSortDirection;

            if (searchValue !== undefined) {
                toolbar.searchInput.value = searchValue;
            }

            if (filterColumn !== undefined && filterValue !== undefined) {
                const filterIndex = resolveColumnIndex(filterColumn);
                const filterInfo = state.filters.find((item) => item.index === filterIndex);
                if (filterInfo && filterInfo.select) {
                    filterInfo.select.value = filterValue;
                }
            }

            if (sortColumn !== undefined) {
                state.sortIndex = resolveColumnIndex(sortColumn);
                state.sortDirection = sortDirectionValue === "desc" ? "desc" : "asc";
            }

            render();
        }

        const shortcutElements = Array.from(document.querySelectorAll(`[data-table-target="#${table.id}"]`));
        shortcutElements.forEach((shortcutElement) => {
            shortcutElement.style.cursor = "pointer";
            shortcutElement.addEventListener("click", () => applyShortcut(shortcutElement));
            shortcutElement.addEventListener("keydown", (event) => {
                if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    applyShortcut(shortcutElement);
                }
            });
        });

        toolbar.searchInput.addEventListener("input", () => {
            state.searchValue = toolbar.searchInput.value;
            render();
        });

        state.filters.forEach((filterInfo) => {
            filterInfo.select.addEventListener("change", render);
        });

        toolbar.clearButton.addEventListener("click", () => {
            toolbar.searchInput.value = "";
            state.filters.forEach((filterInfo) => {
                filterInfo.select.value = "all";
            });
            state.sortIndex = 0;
            state.sortDirection = "asc";
            render();
        });

        headers.forEach((header) => {
            header.cell.style.cursor = ignoredHeaders.has(header.label) ? "default" : "pointer";
            if (ignoredHeaders.has(header.label)) {
                return;
            }

            header.cell.addEventListener("click", () => {
                if (state.sortIndex === header.index) {
                    state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
                } else {
                    state.sortIndex = header.index;
                    state.sortDirection = "asc";
                }
                render();
            });
        });

        render();
    }

    document.querySelectorAll("table[data-enhance-table]").forEach((table) => {
        enhanceTable(table);
    });
});