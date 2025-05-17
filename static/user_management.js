// Static/user_management.js

document.addEventListener('DOMContentLoaded', function() {
    // Enable debug logging to troubleshoot API requests
    addDebugLogging();

    // DOM elements
    const searchBox = document.getElementById('search-box');
    const addUserButton = document.getElementById('add-user-button');
    const userTableBody = document.getElementById('user-table-body');
    const userModal = document.getElementById('user-modal');
    const userForm = document.getElementById('user-form');
    const modalTitle = document.getElementById('modal-title');
    const submitUserBtn = document.getElementById('submit-user-btn');
    const confirmModal = document.getElementById('confirm-modal');
    const confirmMessage = document.getElementById('confirm-message');
    const confirmAction = document.getElementById('confirm-action');
    const cancelAction = document.getElementById('cancel-action');
    const errorMessage = document.getElementById('error-message');
    const successMessage = document.getElementById('success-message');
    
    // Close buttons
    const closeButtons = document.querySelectorAll('.close');
    const cancelButtons = document.querySelectorAll('.cancel-button');
    
    // Current action state
    let currentActionState = {
        action: null,
        userId: null
    };

    // Override fetch to automatically include CSRF tokens
    const originalFetch = window.fetch;
    window.fetch = function(url, options = {}) {
        // Create a new options object
        const newOptions = { ...options };
        
        // Add headers if they don't exist
        newOptions.headers = newOptions.headers || {};
        
        // Add CSRF token to all non-GET requests
        if (!newOptions.method || newOptions.method !== 'GET') {
            const token = getCSRFToken();
            if (token) {
                newOptions.headers['X-CSRF-Token'] = token;
                console.log('Adding CSRF token to request:', token.substring(0, 5) + '...');
            } else {
                console.warn('CSRF token not found in cookies. This request might fail.');
            }
        }
        
        return originalFetch(url, newOptions);
    };

    // Get CSRF token for secure requests
    function getCSRFToken() {
        const token = document.cookie.split('; ')
            .find(row => row.startsWith('csrf_token='))
            ?.split('=')[1];
        
        // Also check for a meta tag as a fallback
        if (!token) {
            const metaTag = document.querySelector('meta[name="csrf-token"]');
            if (metaTag) {
                return metaTag.getAttribute('content');
            }
        }
        
        return token;
    }
    
    // Add event listeners
    
    // Search functionality
    searchBox.addEventListener('input', function() {
        const searchTerm = this.value.toLowerCase();
        filterUsers(searchTerm);
    });
    
    // Open add user modal
    addUserButton.addEventListener('click', function() {
        openUserModal();
    });
    
    // Submit user form
    userForm.addEventListener('submit', function(e) {
        e.preventDefault();
        submitUserForm();
    });
    
    // Close modals when clicking close button
    closeButtons.forEach(button => {
        button.addEventListener('click', function() {
            closeModals();
        });
    });
    
    // Close modals when clicking cancel
    cancelButtons.forEach(button => {
        button.addEventListener('click', function() {
            closeModals();
        });
    });
    
    // Handle table actions (edit, enable/disable, delete)
    userTableBody.addEventListener('click', function(e) {
        // Find the closest button if icon was clicked
        const button = e.target.closest('.action-button');
        if (!button) return;
        
        if (button.classList.contains('edit-button')) {
            const userId = button.dataset.userId;
            openEditUserModal(userId);
        } else if (button.classList.contains('enable-button') || button.classList.contains('disable-button')) {
            const userId = button.dataset.userId;
            const currentStatus = button.dataset.currentStatus;
            openStatusConfirmationModal(userId, currentStatus);
        } else if (button.classList.contains('delete-button')) {
            const userId = button.dataset.userId;
            openDeleteConfirmationModal(userId);
        }
    });
    
    // Confirm action button
    confirmAction.addEventListener('click', function() {
        executeCurrentAction();
    });
    
    // Cancel confirmation
    cancelAction.addEventListener('click', function() {
        closeModals();
    });
    
    // Helper function to handle fetch responses
    function handleFetchResponse(response, errorMsg) {
        console.log('Response status:', response.status);
        const contentType = response.headers.get('content-type');
        console.log('Response content-type:', contentType);
        
        // Handle specific status codes
        if (response.status === 403) {
            // Check if this is a CSRF error
            return response.text().then(text => {
                console.log('403 Response text:', text.substring(0, 200));
                try {
                    const errorData = JSON.parse(text);
                    if (errorData.code === 'csrf_failed' || text.includes('CSRF token')) {
                        console.error('CSRF validation failed');
                        showCSRFErrorModal();
                        throw new Error('Security validation failed. Please try refreshing the page.');
                    } else {
                        throw new Error(errorData.message || 'Access denied. You may not have permission for this action.');
                    }
                } catch (e) {
                    if (e.message.includes('Security validation failed')) {
                        throw e;
                    }
                    throw new Error('Access denied. You may not have permission for this action.');
                }
            });
        }
        
        if (response.status === 401) {
            // Handle authentication errors
            showAuthErrorModal();
            throw new Error('Your session has expired. Please log in again.');
        }
        
        if (!response.ok) {
            return response.text().then(text => {
                console.error('Error response:', text.substring(0, 200));
                // Check if the response is HTML
                if (text.trim().startsWith('<!DOCTYPE html>') || text.trim().startsWith('<html>')) {
                    if (text.includes('login') || text.includes('sign in')) {
                        showAuthErrorModal();
                        throw new Error('Your session has expired. Please log in again.');
                    }
                    throw new Error('Received HTML instead of JSON. Your session may have expired.');
                }
                // Try to parse as JSON if possible
                try {
                    const errorData = JSON.parse(text);
                    throw new Error(errorData.message || errorMsg);
                } catch (e) {
                    // If parsing fails, throw a generic error
                    if (e.message.includes('Your session has expired')) {
                        throw e;
                    }
                    throw new Error(`${errorMsg}: Server returned an invalid response`);
                }
            });
        }
        
        // Check if content type is JSON
        if (!contentType || !contentType.includes('application/json')) {
            throw new Error('Received non-JSON response from server');
        }
        
        return response.json();
    }
    
    // Show CSRF error modal
    function showCSRFErrorModal() {
        // Create a modal to explain the CSRF error
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.style.display = 'flex';
        modal.innerHTML = `
            <div class="modal-content">
                <div class="modal-header">
                    <h2>Security Validation Failed</h2>
                    <button type="button" class="close" aria-label="Close">&times;</button>
                </div>
                <div style="padding: 24px;">
                    <p>Your session security token has expired or is invalid. This usually happens when:</p>
                    <ul>
                        <li>Your session has been inactive for too long</li>
                        <li>You've logged in from another browser tab</li>
                        <li>Browser cookies have been cleared</li>
                    </ul>
                    <p>The page will reload to get a fresh security token.</p>
                </div>
                <div class="form-actions" style="margin: 0 24px 24px;">
                    <button type="button" id="refresh-page" class="add-button">Refresh Page</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        
        // Add click handler for close button
        modal.querySelector('.close').addEventListener('click', function() {
            modal.remove();
        });
        
        // Add click handler for refresh button
        modal.querySelector('#refresh-page').addEventListener('click', function() {
            window.location.reload();
        });
        
        // Auto-reload after 5 seconds
        setTimeout(() => {
            window.location.reload();
        }, 5000);
    }
    
    // Show authentication error modal
    function showAuthErrorModal() {
        // Create a modal to explain the authentication error
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.style.display = 'flex';
        modal.innerHTML = `
            <div class="modal-content">
                <div class="modal-header">
                    <h2>Session Expired</h2>
                    <button type="button" class="close" aria-label="Close">&times;</button>
                </div>
                <div style="padding: 24px;">
                    <p>Your session has expired. You need to log in again to continue.</p>
                </div>
                <div class="form-actions" style="margin: 0 24px 24px;">
                    <button type="button" id="login-redirect" class="add-button">Log In</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        
        // Add click handler for close button
        modal.querySelector('.close').addEventListener('click', function() {
            modal.remove();
        });
        
        // Add click handler for login button
        modal.querySelector('#login-redirect').addEventListener('click', function() {
            window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname);
        });
    }
    
    // Functions
    
    // Filter users in the table based on search term
    function filterUsers(searchTerm) {
        const rows = userTableBody.querySelectorAll('tr');
        
        rows.forEach(row => {
            if (row.querySelector('.empty-table-message')) {
                return; // Skip the "No users found" row
            }
            
            const studentId = row.cells[0].textContent.toLowerCase();
            const name = row.cells[1].textContent.toLowerCase();
            const email = row.cells[2].textContent.toLowerCase();
            
            if (studentId.includes(searchTerm) || 
                name.includes(searchTerm) || 
                email.includes(searchTerm)) {
                row.style.display = '';
            } else {
                row.style.display = 'none';
            }
        });
    }
    
    // Open modal to add a new user
    function openUserModal() {
        resetForm();
        modalTitle.textContent = 'Add New User';
        submitUserBtn.textContent = 'Add User';
        userModal.style.display = 'flex'; // Changed to flex for better centering
    }
    
    // Open modal to edit an existing user
    function openEditUserModal(userId) {
        resetForm();
        modalTitle.textContent = 'Edit User';
        submitUserBtn.textContent = 'Save Changes';
        
        // Get user data
        fetch(`/api/users/${userId}`)
            .then(response => handleFetchResponse(response, 'Failed to fetch user data'))
            .then(user => {
                // Populate form fields
                document.getElementById('user-id').value = user._id;
                document.getElementById('student-id').value = user.student_id || '';
                
                // Handle name field (could be full_name or first_name + last_name)
                if (user.full_name) {
                    document.getElementById('name').value = user.full_name;
                } else if (user.first_name && user.last_name) {
                    document.getElementById('name').value = `${user.first_name} ${user.last_name}`;
                } else if (user.first_name) {
                    document.getElementById('name').value = user.first_name;
                } else {
                    document.getElementById('name').value = '';
                }
                
                document.getElementById('email').value = user.email || '';
                
                // Password field is empty when editing
                document.getElementById('password').value = '';
                document.getElementById('password').required = false;
                
                userModal.style.display = 'flex';
            })
            .catch(error => {
                showError('Error loading user data: ' + error.message);
            });
    }
    
    // Open confirmation modal for enabling/disabling a user
    function openStatusConfirmationModal(userId, currentStatus) {
        const newStatus = currentStatus === 'Active' ? 'Inactive' : 'Active';
        const action = currentStatus === 'Active' ? 'disable' : 'enable';
        
        confirmMessage.textContent = `Are you sure you want to ${action} this user?`;
        confirmAction.textContent = 'Confirm';
        confirmAction.classList.remove('danger-button');
        
        currentActionState = {
            action: 'updateStatus',
            userId: userId,
            newStatus: newStatus
        };
        
        confirmModal.style.display = 'flex';
    }
    
    // Open confirmation modal for deleting a user
    function openDeleteConfirmationModal(userId) {
        confirmMessage.textContent = 'Are you sure you want to delete this user? This action cannot be undone.';
        confirmAction.textContent = 'Delete';
        confirmAction.classList.add('danger-button');
        
        currentActionState = {
            action: 'deleteUser',
            userId: userId
        };
        
        confirmModal.style.display = 'flex';
    }
    
    // Execute the current action (status change or delete)
    function executeCurrentAction() {
        if (currentActionState.action === 'updateStatus') {
            updateUserStatus(currentActionState.userId, currentActionState.newStatus);
        } else if (currentActionState.action === 'deleteUser') {
            deleteUser(currentActionState.userId);
        }
        
        closeModals();
    }
    
    // Submit the user form (add or edit)
    function submitUserForm() {
        // Clear previous errors
        clearFormErrors();
        
        const userId = document.getElementById('user-id').value;
        const studentId = document.getElementById('student-id').value;
        const nameValue = document.getElementById('name').value;
        const email = document.getElementById('email').value;
        const password = document.getElementById('password').value;
        
        // Basic validation
        let hasErrors = false;
        
        if (!studentId) {
            showFieldError('student-id-error', 'Student ID is required');
            hasErrors = true;
        }
        
        if (!nameValue) {
            showFieldError('name-error', 'Name is required');
            hasErrors = true;
        }
        
        if (!email) {
            showFieldError('email-error', 'Email is required');
            hasErrors = true;
        } else if (!isValidEmail(email)) {
            showFieldError('email-error', 'Please enter a valid email address');
            hasErrors = true;
        }
        
        if (!userId && !password) {
            showFieldError('password-error', 'Password is required for new users');
            hasErrors = true;
        }
        
        if (hasErrors) {
            return;
        }
        
        // Split name into first and last name
        let firstName = '';
        let lastName = '';
        
        const nameParts = nameValue.trim().split(' ');
        if (nameParts.length >= 2) {
            firstName = nameParts[0];
            lastName = nameParts.slice(1).join(' ');
        } else {
            firstName = nameValue;
            lastName = '';
        }
        
        // Prepare data
        const userData = {
            student_id: studentId,
            first_name: firstName,
            last_name: lastName,
            email: email
        };
        
        if (password) {
            userData.password = password;
        }
        
        // Add or update user
        if (!userId) {
            // Add new user
            addUser(userData);
        } else {
            // Update existing user
            updateUser(userId, userData);
        }
    }
    
    // Add a new user
    function addUser(userData) {
        fetch('/api/users', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
                // CSRF token will be added automatically by our fetch override
            },
            body: JSON.stringify(userData)
        })
        .then(response => handleFetchResponse(response, 'Failed to add user'))
        .then(user => {
            closeModals();
            showSuccess('User added successfully!');
            // Refresh the user list or add the new user to the table
            refreshUserTable();
        })
        .catch(error => {
            showError(error.message);
        });
    }
    
    // Update an existing user
    function updateUser(userId, userData) {
        fetch(`/api/users/${userId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
                // CSRF token will be added automatically by our fetch override
            },
            body: JSON.stringify(userData)
        })
        .then(response => handleFetchResponse(response, 'Failed to update user'))
        .then(user => {
            closeModals();
            showSuccess('User updated successfully!');
            // Refresh the user list
            refreshUserTable();
        })
        .catch(error => {
            showError(error.message);
        });
    }
    
    // Update a user's status
    function updateUserStatus(userId, newStatus) {
        fetch(`/api/users/${userId}/status`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
                // CSRF token will be added automatically by our fetch override
            },
            body: JSON.stringify({ status: newStatus })
        })
        .then(response => handleFetchResponse(response, 'Failed to update user status'))
        .then(user => {
            showSuccess(`User ${newStatus === 'Active' ? 'enabled' : 'disabled'} successfully!`);
            // Refresh the table
            refreshUserTable();
        })
        .catch(error => {
            showError(error.message);
        });
    }
    
    // Delete a user
    function deleteUser(userId) {
        fetch(`/api/users/${userId}`, {
            method: 'DELETE'
            // CSRF token will be added automatically by our fetch override
        })
        .then(response => handleFetchResponse(response, 'Failed to delete user'))
        .then(result => {
            if (result.success) {
                showSuccess('User deleted successfully!');
                // Remove the user from the table
                const row = userTableBody.querySelector(`tr[data-user-id="${userId}"]`);
                if (row) {
                    row.remove();
                }
                // Check if table is empty
                if (userTableBody.children.length === 0) {
                    userTableBody.innerHTML = `
                        <tr>
                            <td colspan="6" class="empty-table-message">No users found</td>
                        </tr>
                    `;
                }
            } else {
                throw new Error(result.message || 'Failed to delete user');
            }
        })
        .catch(error => {
            showError(error.message);
        });
    }
    
    // Refresh the user table
    function refreshUserTable() {
        // Simple approach: reload the page
        window.location.reload();
        
        // Alternatively, fetch users and update the table dynamically
        /* 
        fetch('/api/users')
            .then(response => handleFetchResponse(response, 'Error refreshing user data'))
            .then(users => {
                updateTableWithUsers(users);
            })
            .catch(error => {
                showError('Error refreshing user data: ' + error.message);
            });
        */
    }
    
    // Update the table with new user data
    function updateTableWithUsers(users) {
        if (!users || users.length === 0) {
            userTableBody.innerHTML = `
                <tr>
                    <td colspan="6" class="empty-table-message">No users found</td>
                </tr>
            `;
            return;
        }
        
        userTableBody.innerHTML = '';
        
        users.forEach(user => {
            // Determine the name to display
            let displayName = '';
            if (user.full_name) {
                displayName = user.full_name;
            } else if (user.first_name && user.last_name) {
                displayName = `${user.first_name} ${user.last_name}`;
            } else if (user.first_name) {
                displayName = user.first_name;
            } else {
                displayName = user.email || 'Unknown';
            }
            
            const status = user.status || 'Inactive';
            
            const row = document.createElement('tr');
            row.dataset.userId = user._id;
            
            row.innerHTML = `
                <td>${user.student_id || ''}</td>
                <td>${displayName}</td>
                <td>${user.email || ''}</td>
                <td>${user.last_login || 'Never'}</td>
                <td>
                    <span class="status-badge ${status === 'Active' ? 'status-active' : 'status-inactive'}">
                        ${status}
                    </span>
                </td>
                <td>
                    <div class="action-buttons">
                        <button class="action-button edit-button" 
                                data-user-id="${user._id}"
                                aria-label="Edit user">
                            <i class="fas fa-edit"></i>
                        </button>
                        <button class="action-button ${status === 'Active' ? 'disable-button' : 'enable-button'}" 
                                data-user-id="${user._id}"
                                data-current-status="${status}"
                                aria-label="${status === 'Active' ? 'Disable' : 'Enable'} user">
                            <i class="fas ${status === 'Active' ? 'fa-ban' : 'fa-check-circle'}"></i>
                        </button>
                        <button class="action-button delete-button" 
                                data-user-id="${user._id}"
                                aria-label="Delete user">
                            <i class="fas fa-trash-alt"></i>
                        </button>
                    </div>
                </td>
            `;
            
            userTableBody.appendChild(row);
        });
    }
    
    // Helper functions
    
    // Reset the user form
    function resetForm() {
        userForm.reset();
        document.getElementById('user-id').value = '';
        document.getElementById('password').required = true;
        clearFormErrors();
    }
    
    // Close all modals
    function closeModals() {
        userModal.style.display = 'none';
        confirmModal.style.display = 'none';
        // Reset confirm action button
        confirmAction.classList.remove('danger-button');
        resetForm();
    }
    
    // Show an error message
    function showError(message) {
        errorMessage.textContent = message;
        errorMessage.style.display = 'block';
        
        // Hide after 5 seconds
        setTimeout(() => {
            errorMessage.style.display = 'none';
        }, 5000);
    }
    
    // Show a success message
    function showSuccess(message) {
        successMessage.textContent = message;
        successMessage.style.display = 'block';
        
        // Hide after 5 seconds
        setTimeout(() => {
            successMessage.style.display = 'none';
        }, 5000);
    }
    
    // Show a field-specific error
    function showFieldError(elementId, message) {
        const errorElement = document.getElementById(elementId);
        if (errorElement) {
            errorElement.textContent = message;
            errorElement.style.display = 'block';
        }
    }
    
    // Clear all form errors
    function clearFormErrors() {
        const errorElements = document.querySelectorAll('.error-feedback');
        errorElements.forEach(element => {
            element.textContent = '';
            element.style.display = 'none';
        });
    }
    
    // Validate email format
    function isValidEmail(email) {
        const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return re.test(email);
    }
    
    // Add debugging code to help identify issues
    function addDebugLogging() {
        const originalFetch = window.fetch;
        window.fetch = function(url, options) {
            console.log('Fetch request to:', url, options);
            return originalFetch(url, options)
                .then(response => {
                    console.log('Fetch response from:', url, 'Status:', response.status);
                    console.log('Content-Type:', response.headers.get('content-type'));
                    return response;
                })
                .catch(error => {
                    console.error('Fetch error for:', url, error);
                    throw error;
                });
        };

        // Also log all CSRF tokens for debugging
        console.log('CSRF Token in cookies:', getCSRFToken());
        
        // Check for CSRF meta tag
        const metaTag = document.querySelector('meta[name="csrf-token"]');
        if (metaTag) {
            console.log('CSRF Token in meta tag:', metaTag.getAttribute('content'));
        } else {
            console.log('No CSRF meta tag found');
        }
    }
});