// Aditya L&D System Main JavaScript

// Theme Initialization & Management
(function () {
    if (document.documentElement.hasAttribute('data-theme') && document.documentElement.getAttribute('data-theme')) {
        return;
    }
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme) {
        document.documentElement.setAttribute('data-theme', savedTheme);
    } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        document.documentElement.setAttribute('data-theme', 'dark');
    } else {
        document.documentElement.setAttribute('data-theme', 'light');
    }
})();

document.addEventListener('DOMContentLoaded', function () {
    // Sync Theme Toggle UI
    updateThemeToggleUI();

    // Move all modals to body to prevent z-index and backdrop click issues
    document.querySelectorAll('.modal').forEach(modal => {
        document.body.appendChild(modal);
    });

    // Attach click listeners to theme toggle buttons
    const themeButtons = document.querySelectorAll('.theme-toggle-btn');
    themeButtons.forEach(btn => {
        btn.addEventListener('click', function (e) {
            e.preventDefault();
            toggleTheme();
        });
    });

    // Profile Sidebar Expand / Collapse Toggle Handler
    setupSidebarToggle();

    // Dummy Header Tabs View Handler
    setupDummyHeaderTabs();

    // Sidebar toggle handler (Admin mode)
    const sidebarToggle = document.getElementById('sidebarToggle');
    if (sidebarToggle) {
        sidebarToggle.addEventListener('click', function (e) {
            e.preventDefault();
            document.getElementById('wrapper').classList.toggle('toggled');
        });
    }

    // Auto dismiss toasts after 4 seconds
    const toastElList = [].slice.call(document.querySelectorAll('.toast'));
    toastElList.map(function (toastEl) {
        return new bootstrap.Toast(toastEl, { delay: 4000 }).show();
    });

    // Dynamic fields for Live Class (Online vs In Person)
    const classModeSelect = document.getElementById('class_mode');
    if (classModeSelect) {
        function toggleModeFields() {
            const mode = classModeSelect.value;
            const inPersonFields = document.querySelectorAll('.in-person-field');
            const onlineFields = document.querySelectorAll('.online-field');

            if (mode === 'Online') {
                inPersonFields.forEach(el => el.style.display = 'none');
                onlineFields.forEach(el => el.style.display = 'block');
            } else {
                inPersonFields.forEach(el => el.style.display = 'block');
                onlineFields.forEach(el => el.style.display = 'none');
            }
        }
        classModeSelect.addEventListener('change', toggleModeFields);
        toggleModeFields();
    }

    // Initialize Search Functionality & Instant Live Filtering
    setupSearchInputs();
    setupGlobalSearchModal();
});

// Sidebar Expand / Collapse Logic
function setupSidebarToggle() {
    const toggleBtn = document.getElementById('toggleSidebarBtn');
    const toggleFooterBtn = document.getElementById('toggleSidebarFooterBtn');
    const sidebar = document.getElementById('learnerSidebar');
    const sidebarCol = document.getElementById('sidebarCol');
    const mainCol = document.getElementById('mainContentCol');
    const icon = document.getElementById('toggleSidebarIcon');
    const text = document.getElementById('toggleSidebarText');
    const footerText = document.getElementById('toggleSidebarFooterText');

    if (sidebar) {
        function setCollapsedState(collapsed) {
            if (collapsed) {
                sidebar.classList.add('collapsed');
                if (sidebarCol) sidebarCol.className = 'col-12 col-lg-2 col-xl-2 sidebar-col';
                if (mainCol) mainCol.className = 'col-12 col-lg-7 col-xl-7 main-content-col';
                if (icon) icon.className = 'fa-solid fa-angles-right';
                if (text) text.innerText = '';
                if (footerText) footerText.innerText = 'Expand';
            } else {
                sidebar.classList.remove('collapsed');
                if (sidebarCol) sidebarCol.className = 'col-12 col-lg-3 col-xl-3 sidebar-col';
                if (mainCol) mainCol.className = 'col-12 col-lg-6 col-xl-6 main-content-col';
                if (icon) icon.className = 'fa-solid fa-angles-left';
                if (text) text.innerText = 'Collapse';
                if (footerText) footerText.innerText = 'Collapse';
            }
        }

        // Default to uncollapsed (full 3-column 25% width)
        localStorage.removeItem('sidebar_collapsed');
        setCollapsedState(false);

        const handleToggle = function (e) {
            e.preventDefault();
            const nextState = !sidebar.classList.contains('collapsed');
            setCollapsedState(nextState);
            localStorage.setItem('sidebar_collapsed', nextState);
        };

        if (toggleBtn) toggleBtn.addEventListener('click', handleToggle);
        if (toggleFooterBtn) toggleFooterBtn.addEventListener('click', handleToggle);
    }

    // Mobile Profile Expand / Collapse Toggle Bar Listener
    const mobileProfileBtn = document.getElementById('mobileProfileToggleBtn');
    const sidebarStatsContainer = document.getElementById('sidebarStatsContainer');
    const mobileProfileIcon = document.getElementById('mobileProfileToggleIcon');

    if (mobileProfileBtn && sidebarStatsContainer) {
        mobileProfileBtn.addEventListener('click', function(e) {
            e.preventDefault();
            sidebarStatsContainer.classList.toggle('mobile-show');
            if (mobileProfileIcon) {
                if (sidebarStatsContainer.classList.contains('mobile-show')) {
                    mobileProfileIcon.className = 'fa-solid fa-chevron-up text-teal';
                } else {
                    mobileProfileIcon.className = 'fa-solid fa-chevron-down text-teal';
                }
            }
        });
    }
}

// Dummy Header Tabs Handlers
function setupDummyHeaderTabs() {
    const dummyTabs = document.querySelectorAll('.dummy-nav-tab');
    dummyTabs.forEach(tab => {
        tab.addEventListener('click', function (e) {
            e.preventDefault();
            document.querySelectorAll('.ls-nav-tab').forEach(t => t.classList.remove('active'));
            this.classList.add('active');

            const tabName = this.getAttribute('data-tab-name') || 'Dummy View';
            showDummyModal(tabName);
        });
    });
}

// Modal View Trigger for Dummy Header Tabs
function showDummyModal(tabName) {
    let existingModal = document.getElementById('dummyTabModal');
    if (existingModal) existingModal.remove();

    const modalHTML = `
    <div class="modal fade" id="dummyTabModal" tabindex="-1" aria-hidden="true">
        <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content border-0 shadow-lg rounded-4">
                <div class="modal-header border-0 pb-0">
                    <h5 class="modal-title fw-bold text-dark"><i class="fa-solid fa-layer-group text-primary me-2"></i> ${tabName}</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                </div>
                <div class="modal-body text-center py-4">
                    <div class="bg-primary-subtle text-primary rounded-circle p-3 d-inline-flex mb-3">
                        <i class="fa-solid fa-laptop-code fs-2"></i>
                    </div>
                    <h6 class="fw-bold text-dark mb-2">${tabName} Preview Panel</h6>
                    <p class="text-muted small mb-0">This tab view is configured as an interactive preview panel for the Aditya L&D Management System.</p>
                </div>
                <div class="modal-footer border-0 pt-0">
                    <button type="button" class="btn btn-primary w-100 fw-bold" data-bs-dismiss="modal">Close View</button>
                </div>
            </div>
        </div>
    </div>`;

    document.body.insertAdjacentHTML('beforeend', modalHTML);
    const modal = new bootstrap.Modal(document.getElementById('dummyTabModal'));
    modal.show();
}

// Toggle Theme Function
function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    updateThemeToggleUI();
}

// Update Theme Toggle Buttons UI
function updateThemeToggleUI() {
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
    const themeButtons = document.querySelectorAll('.theme-toggle-btn');
    
    themeButtons.forEach(btn => {
        if (currentTheme === 'dark') {
            btn.innerHTML = `<i class="fa-solid fa-sun text-warning me-0 me-md-1"></i> <span class="d-none d-md-inline">Light Mode</span>`;
            btn.setAttribute('aria-label', 'Switch to Light Theme');
        } else {
            btn.innerHTML = `<i class="fa-solid fa-moon text-primary me-0 me-md-1"></i> <span class="d-none d-md-inline">Dark Mode</span>`;
            btn.setAttribute('aria-label', 'Switch to Dark Theme');
        }
    });
}

// Dynamic AJAX unlock function for locked Live Classes
function submitUnlockClass(classIdStr) {
    const reasonInput = document.getElementById('unlockReasonInput');
    const reason = reasonInput ? reasonInput.value.trim() : '';

    if (!reason) {
        alert('Mandatory reason for unlocking class must be provided.');
        return;
    }

    const formData = new FormData();
    formData.append('class_id', classIdStr);
    formData.append('reason', reason);

    fetch('/classes/unlock', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert(data.message);
            location.reload();
        } else {
            alert('Error: ' + data.message);
        }
    })
    .catch(err => {
        alert('Failed to unlock class: ' + err);
    });
}

// Universal Search Inputs & Real-time Table Filtering Engine
function setupSearchInputs() {
    const searchBoxes = document.querySelectorAll('.ls-search-box, input[name="search"]');
    
    searchBoxes.forEach(container => {
        let input = container.tagName === 'INPUT' ? container : container.querySelector('input');
        if (!input) return;

        let clearBtn = container.querySelector ? container.querySelector('.ls-search-clear') : null;
        let form = input.closest('form');
        let selectFilter = form ? form.querySelector('select[name="mode"], select[name="class_id"]') : null;

        function filterTableRows() {
            const tableRows = document.querySelectorAll('tbody tr');
            const rawQuery = input.value.trim();
            const lowerQuery = rawQuery.toLowerCase();
            const keywords = lowerQuery.split(/\s+/).filter(k => k.length > 0);
            const selectedMode = selectFilter ? selectFilter.value.trim().toLowerCase() : '';

            // Toggle Clear Button
            if (clearBtn) {
                clearBtn.style.display = lowerQuery.length > 0 ? 'flex' : 'none';
            }

            if (tableRows.length > 0) {
                let matchCount = 0;

                tableRows.forEach(row => {
                    if (row.classList.contains('no-search-results-row')) return;

                    // Extract visible cell content text cleanly (case-insensitive)
                    const cellText = Array.from(row.children)
                        .map(td => (td.innerText || td.textContent || '').trim())
                        .join(' ')
                        .toLowerCase()
                        .replace(/\s+/g, ' ');

                    // Check keyword matches (all keywords must exist in cell text)
                    const queryMatches = keywords.length === 0 || keywords.every(kw => cellText.includes(kw));

                    // Check mode dropdown match if active
                    let modeMatches = true;
                    if (selectedMode && selectedMode !== 'all' && selectedMode !== '') {
                        modeMatches = cellText.includes(selectedMode);
                    }

                    if (queryMatches && modeMatches) {
                        row.style.display = '';
                        matchCount++;
                    } else {
                        row.style.display = 'none';
                    }
                });

                // Handle empty state row
                let emptyRow = document.querySelector('.no-search-results-row');
                if (matchCount === 0 && (keywords.length > 0 || (selectedMode && selectedMode !== 'all'))) {
                    if (!emptyRow && tableRows[0] && tableRows[0].parentElement) {
                        const colCount = tableRows[0].children.length || 6;
                        const tr = document.createElement('tr');
                        tr.className = 'no-search-results-row';
                        tr.innerHTML = `<td colspan="${colCount}" class="text-center py-4 text-muted"><i class="fa-solid fa-magnifying-glass me-2 text-teal"></i> No matching records found for "<strong>${escapeHtml(rawQuery)}</strong>"</td>`;
                        tableRows[0].parentElement.appendChild(tr);
                    } else if (emptyRow) {
                        emptyRow.style.display = '';
                    }
                } else if (emptyRow) {
                    emptyRow.style.display = 'none';
                }
            }
        }

        // Live input & keyup events
        input.addEventListener('input', filterTableRows);
        input.addEventListener('keyup', filterTableRows);

        // Mode dropdown live change event
        if (selectFilter) {
            selectFilter.addEventListener('change', filterTableRows);
        }

        // Clear button click handler
        if (clearBtn) {
            clearBtn.addEventListener('click', function (e) {
                e.preventDefault();
                input.value = '';
                if (window.location.search.includes('search=')) {
                    const url = new URL(window.location.href);
                    url.searchParams.delete('search');
                    window.history.replaceState({}, '', url.toString());
                }
                filterTableRows();
                input.focus();
            });
        }

        // Run filter immediately on load
        filterTableRows();
    });
}

// Global Portal Search Modal Handler
function setupGlobalSearchModal() {
    const searchInput = document.getElementById('globalSearchInput');
    const searchClear = document.getElementById('globalSearchClear');
    const searchResults = document.getElementById('globalSearchResults');
    const modalEl = document.getElementById('globalSearchModal');

    if (!searchInput || !searchResults) return;

    // Keyboard Shortcut (Ctrl+K or / to open Search)
    document.addEventListener('keydown', function (e) {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
            e.preventDefault();
            if (modalEl) {
                const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
                modal.show();
            }
        }
    });

    if (modalEl) {
        modalEl.addEventListener('shown.bs.modal', function () {
            searchInput.focus();
        });
    }

    searchInput.addEventListener('input', function () {
        const query = this.value.toLowerCase().trim();

        if (searchClear) {
            searchClear.style.display = query.length > 0 ? 'flex' : 'none';
        }

        if (!query) {
            searchResults.innerHTML = `
                <div class="text-center py-4 text-muted">
                    <i class="fa-solid fa-graduation-cap display-4 text-teal opacity-50 mb-2"></i>
                    <h6 class="fw-bold text-dark mb-1">Instant Portal Search</h6>
                    <p class="small text-muted mb-0">Type keywords above to search across Courses, Classes, Learners, and Certificates...</p>
                </div>`;
            return;
        }

        // Collect all navigable items from navigation, tables, and portal options
        let matches = [];

        // 1. Navigation items
        const navTabs = document.querySelectorAll('.ls-nav-tab, .dropdown-item');
        navTabs.forEach(tab => {
            const text = tab.innerText.trim();
            const href = tab.getAttribute('href');
            if (text && href && href !== '#' && text.toLowerCase().includes(query)) {
                matches.push({ title: text, type: 'Page Navigation', href: href, icon: 'fa-compass' });
            }
        });

        // 2. Table rows (Courses, Classes, Learners, Certificates)
        const rows = document.querySelectorAll('tbody tr');
        rows.forEach(row => {
            const text = row.innerText.trim();
            if (text && text.toLowerCase().includes(query)) {
                const firstLink = row.querySelector('a[href]');
                const titleEl = row.querySelector('.fw-bold, td:first-child');
                const titleText = titleEl ? titleEl.innerText.trim() : text.substring(0, 40);
                const href = firstLink ? firstLink.getAttribute('href') : window.location.href;

                let icon = 'fa-file-lines';
                if (titleText.startsWith('CRS-') || text.includes('Course')) icon = 'fa-book-open';
                else if (titleText.startsWith('CLS-') || text.includes('Class')) icon = 'fa-chalkboard-user';
                else if (text.includes('Learner') || titleText.match(/^\d+$/)) icon = 'fa-user';
                else if (text.includes('Cert')) icon = 'fa-certificate';

                matches.push({
                    title: titleText,
                    type: 'Record Match',
                    subtitle: text.substring(0, 90).replace(/\s+/g, ' '),
                    href: href,
                    icon: icon
                });
            }
        });

        // Deduplicate matches by title + href
        const uniqueMatches = [];
        const seen = new Set();
        matches.forEach(m => {
            const key = m.title + '|' + m.href;
            if (!seen.has(key)) {
                seen.add(key);
                uniqueMatches.push(m);
            }
        });

        if (uniqueMatches.length === 0) {
            searchResults.innerHTML = `
                <div class="text-center py-4 text-muted">
                    <i class="fa-solid fa-face-frown fs-2 mb-2 text-warning"></i>
                    <h6 class="fw-bold text-dark mb-1">No results found for "${escapeHtml(query)}"</h6>
                    <p class="small text-muted mb-0">Try searching for course codes (e.g. CRS-000001), learner names, or page titles.</p>
                </div>`;
        } else {
            let html = '<div class="list-group list-group-flush">';
            uniqueMatches.slice(0, 8).forEach(item => {
                html += `
                <a href="${item.href}" class="list-group-item list-group-item-action p-3 rounded-3 mb-2 border text-start d-flex align-items-center justify-content-between text-decoration-none">
                    <div class="d-flex align-items-center gap-3">
                        <div class="badge bg-teal-subtle text-teal p-2.5 rounded-circle fs-5 d-flex align-items-center justify-content-center" style="width: 40px; height: 40px;">
                            <i class="fa-solid ${item.icon}"></i>
                        </div>
                        <div>
                            <div class="fw-bold text-dark fs-6 mb-0">${escapeHtml(item.title)}</div>
                            <small class="text-muted text-xs">${escapeHtml(item.subtitle || item.type)}</small>
                        </div>
                    </div>
                    <i class="fa-solid fa-chevron-right text-teal small"></i>
                </a>`;
            });
            html += '</div>';
            searchResults.innerHTML = html;
        }
    });

    if (searchClear) {
        searchClear.addEventListener('click', function () {
            searchInput.value = '';
            searchInput.dispatchEvent(new Event('input'));
            searchInput.focus();
        });
    }
}

// Utility to escape HTML strings safely
function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
