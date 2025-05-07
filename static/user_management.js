// Static/user_management.js

document.addEventListener('DOMContentLoaded', function() {
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

    // Get CSRF token for secure requests
    function getCSRFToken() {
        return document.cookie.split('; ')
            .find(row => row.startsWith('csrf_token='))
            ?.split('=')[1];
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
        if (e.target.matches('.edit-button')) {
            const userId = e.target.dataset.userId;
            openEditUserModal(userId);
        } else if (e.target.matches('.enable-button, .disable-button')) {
            const userId = e.target.dataset.userId;
            const currentStatus = e.target.dataset.currentStatus;
            openStatusConfirmationModal(userId, currentStatus);
        } else if (e.target.matches('.delete-button')) {
            const userId = e.target.dataset.userId;
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
        userModal.style.display = 'block';
    }
    
    // Open modal to edit an existing user
    function openEditUserModal(userId) {
        resetForm();
        modalTitle.textContent = 'Edit User';
        submitUserBtn.textContent = 'Save Changes';
        
        // Get user data
        fetch(`/api/users/${userId}`)
            .then(response => {
                if (!response.ok) {
                    throw new Error('Failed to fetch user data');
                }
                return response.json();
            })
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
                
                userModal.style.display = 'block';
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
        
        currentActionState = {
            action: 'updateStatus',
            userId: userId,
            newStatus: newStatus
        };
        
        confirmModal.style.display = 'block';
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
        
        confirmModal.style.display = 'block';
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
        const csrfToken = getCSRFToken();
        
        fetch('/api/users', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': csrfToken
            },
            body: JSON.stringify(userData)
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(data => {
                    throw new Error(data.message || 'Failed to add user');
                });
            }
            return response.json();
        })
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
        const csrfToken = getCSRFToken();
        
        fetch(`/api/users/${userId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': csrfToken
            },
            body: JSON.stringify(userData)
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(data => {
                    throw new Error(data.message || 'Failed to update user');
                });
            }
            return response.json();
        })
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
        const csrfToken = getCSRFToken();
        
        fetch(`/api/users/${userId}/status`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': csrfToken
            },
            body: JSON.stringify({ status: newStatus })
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(data => {
                    throw new Error(data.message || 'Failed to update user status');
                });
            }
            return response.json();
        })
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
            method: 'DELETE',
            headers: {
                'X-CSRF-Token': getCSRFToken()
            }
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(data => {
                    throw new Error(data.message || 'Failed to delete user');
                });
            }
            return response.json();
        })
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
            .then(response => response.json())
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
                <td class="status-${status === 'Active' ? 'active' : 'inactive'}">${status}</td>
                <td>
                    <button class="action-button edit-button" 
                            data-user-id="${user._id}"
                            aria-label="Edit user">
                        Edit
                    </button>
                    <button class="action-button ${status === 'Active' ? 'disable-button' : 'enable-button'}" 
                            data-user-id="${user._id}"
                            data-current-status="${status}"
                            aria-label="${status === 'Active' ? 'Disable' : 'Enable'} user">
                        ${status === 'Active' ? 'Disable' : 'Enable'}
                    </button>
                    <button class="action-button delete-button" 
                            data-user-id="${user._id}"
                            aria-label="Delete user">
                        Delete
                    </button>
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
});