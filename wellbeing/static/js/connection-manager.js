/**
 * Connection Manager - Frontend JavaScript for Student-Therapist Bridge
 * Handles real-time communication, notifications, and coordination
 */

class ConnectionManager {
    constructor(options = {}) {
        this.studentId = options.studentId;
        this.therapistId = options.therapistId;
        this.userRole = options.userRole;
        this.socketUrl = options.socketUrl || window.location.origin;
        this.apiBase = '/api/connection';
        
        // Socket.IO connection (if available)
        this.socket = null;
        this.roomId = null;
        
        // Event handlers
        this.eventHandlers = {
            'message': [],
            'appointment_updated': [],
            'resource_shared': [],
            'notification': [],
            'connection_status': []
        };
        
        // UI elements
        this.messageContainer = null;
        this.notificationContainer = null;
        this.statusIndicator = null;
        
        // Initialize
        this.init();
    }
    
    async init() {
        try {
            // Get connection details if not provided
            if (!this.studentId || !this.therapistId) {
                await this.getConnectionDetails();
            }
            
            // Setup room ID
            if (this.studentId && this.therapistId) {
                this.roomId = `connection_${Math.min(this.studentId, this.therapistId)}_${Math.max(this.studentId, this.therapistId)}`;
            }
            
            // Initialize Socket.IO if available
            this.initSocket();
            
            // Setup UI
            this.setupUI();
            
            // Load initial data
            await this.loadInitialData();
            
            console.log('Connection Manager initialized', {
                studentId: this.studentId,
                therapistId: this.therapistId,
                userRole: this.userRole,
                roomId: this.roomId
            });
            
        } catch (error) {
            console.error('Failed to initialize Connection Manager:', error);
        }
    }
    
    async getConnectionDetails() {
        try {
            const response = await fetch(`${this.apiBase}/get-navigation-links`);
            const data = await response.json();
            
            this.userRole = data.user_role;
            
            if (data.user_role === 'student' && data.connections.length > 0) {
                const therapist = data.connections.find(c => c.type === 'therapist');
                if (therapist) {
                    this.therapistId = therapist.id;
                }
            } else if (data.user_role === 'therapist') {
                // For therapist, student ID will be set when viewing specific student
                this.therapistId = data.user_id;
            }
            
        } catch (error) {
            console.error('Failed to get connection details:', error);
        }
    }
    
    initSocket() {
        if (typeof io !== 'undefined') {
            try {
                this.socket = io(this.socketUrl);
                
                this.socket.on('connect', () => {
                    console.log('Socket.IO connected');
                    if (this.roomId) {
                        this.joinRoom();
                    }
                });
                
                this.socket.on('disconnect', () => {
                    console.log('Socket.IO disconnected');
                });
                
                // Message events
                this.socket.on('new_message', (data) => {
                    this.handleNewMessage(data);
                });
                
                // Appointment events
                this.socket.on('appointment_updated', (data) => {
                    this.handleAppointmentUpdate(data);
                });
                
                // Resource events
                this.socket.on('resource_shared', (data) => {
                    this.handleResourceShared(data);
                });
                
            } catch (error) {
                console.warn('Socket.IO not available:', error);
            }
        } else {
            console.warn('Socket.IO library not loaded - real-time features disabled');
        }
    }
    
    joinRoom() {
        if (this.socket && this.studentId && this.therapistId) {
            this.socket.emit('join_connection_room', {
                student_id: this.studentId,
                therapist_id: this.therapistId
            });
        }
    }
    
    setupUI() {
        // Create notification container if it doesn't exist
        if (!document.getElementById('connection-notifications')) {
            const notificationContainer = document.createElement('div');
            notificationContainer.id = 'connection-notifications';
            notificationContainer.className = 'fixed top-4 right-4 z-50 space-y-2';
            document.body.appendChild(notificationContainer);
            this.notificationContainer = notificationContainer;
        }
        
        // Setup message container
        this.messageContainer = document.getElementById('message-container');
        
        // Setup status indicator
        this.statusIndicator = document.getElementById('connection-status');
        
        // Add CSS for notifications
        this.addNotificationStyles();
    }
    
    addNotificationStyles() {
        if (document.getElementById('connection-styles')) return;
        
        const style = document.createElement('style');
        style.id = 'connection-styles';
        style.textContent = `
            .connection-notification {
                background: white;
                border-left: 4px solid #3b82f6;
                border-radius: 0.5rem;
                box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
                padding: 1rem;
                max-width: 24rem;
                transform: translateX(100%);
                transition: all 0.3s ease;
            }
            
            .connection-notification.show {
                transform: translateX(0);
            }
            
            .connection-notification.success {
                border-left-color: #10b981;
            }
            
            .connection-notification.error {
                border-left-color: #ef4444;
            }
            
            .connection-notification.warning {
                border-left-color: #f59e0b;
            }
            
            .connection-status-indicator {
                display: inline-flex;
                align-items: center;
                gap: 0.5rem;
                padding: 0.25rem 0.75rem;
                border-radius: 9999px;
                font-size: 0.875rem;
                font-weight: 500;
            }
            
            .connection-status-indicator.connected {
                background-color: #dcfce7;
                color: #166534;
            }
            
            .connection-status-indicator.disconnected {
                background-color: #fee2e2;
                color: #991b1b;
            }
            
            .connection-pulse {
                width: 0.5rem;
                height: 0.5rem;
                border-radius: 50%;
                animation: pulse 2s infinite;
            }
            
            .connection-pulse.connected {
                background-color: #22c55e;
            }
            
            .connection-pulse.disconnected {
                background-color: #ef4444;
            }
            
            @keyframes pulse {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.5; }
            }
        `;
        document.head.appendChild(style);
    }
    
    async loadInitialData() {
        try {
            // Load connection status
            await this.updateConnectionStatus();
            
            // Load unread notifications
            await this.loadNotifications();
            
        } catch (error) {
            console.error('Failed to load initial data:', error);
        }
    }
    
    // === MESSAGING ===
    
    async sendMessage(content, type = 'text', metadata = {}) {
        try {
            const response = await fetch(`${this.apiBase}/send-message`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    student_id: this.studentId,
                    therapist_id: this.therapistId,
                    message: content,
                    type: type,
                    metadata: metadata
                })
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.emit('message', {
                    type: 'sent',
                    content: content,
                    messageType: type,
                    timestamp: data.timestamp,
                    messageId: data.message_id
                });
                
                return data;
            } else {
                throw new Error(data.error || 'Failed to send message');
            }
            
        } catch (error) {
            console.error('Failed to send message:', error);
            this.showNotification('Failed to send message', 'error');
            throw error;
        }
    }
    
    async loadMessages(limit = 50, offset = 0) {
        try {
            const response = await fetch(`${this.apiBase}/get-messages?limit=${limit}&offset=${offset}&student_id=${this.studentId}&therapist_id=${this.therapistId}`);
            const data = await response.json();
            
            if (data.messages) {
                return data;
            } else {
                throw new Error(data.error || 'Failed to load messages');
            }
            
        } catch (error) {
            console.error('Failed to load messages:', error);
            return { messages: [], total_count: 0, has_more: false };
        }
    }
    
    handleNewMessage(data) {
        console.log('New message received:', data);
        
        // Update UI if message container exists
        if (this.messageContainer) {
            this.addMessageToUI(data);
        }
        
        // Show notification if not from current user
        if (data.sender !== this.userRole) {
            this.showNotification('New message received', 'success');
        }
        
        // Emit event for custom handlers
        this.emit('message', {
            type: 'received',
            ...data
        });
    }
    
    addMessageToUI(messageData) {
        if (!this.messageContainer) return;
        
        const messageEl = document.createElement('div');
        messageEl.className = `message ${messageData.sender === this.userRole ? 'sent' : 'received'}`;
        
        messageEl.innerHTML = `
            <div class="message-content">
                <p>${this.escapeHtml(messageData.content)}</p>
                <small class="message-time">${messageData.formatted_time || new Date(messageData.timestamp).toLocaleTimeString()}</small>
            </div>
        `;
        
        this.messageContainer.appendChild(messageEl);
        this.messageContainer.scrollTop = this.messageContainer.scrollHeight;
    }
    
    // === APPOINTMENTS ===
    
    async syncAppointment(appointmentId, action, data = {}) {
        try {
            const response = await fetch(`${this.apiBase}/sync-appointment`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    student_id: this.studentId,
                    therapist_id: this.therapistId,
                    appointment_id: appointmentId,
                    action: action,
                    ...data
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.showNotification(`Appointment ${action} successful`, 'success');
                this.emit('appointment_updated', result);
                return result;
            } else {
                throw new Error(result.error || `Failed to ${action} appointment`);
            }
            
        } catch (error) {
            console.error(`Failed to ${action} appointment:`, error);
            this.showNotification(`Failed to ${action} appointment`, 'error');
            throw error;
        }
    }
    
    async loadAppointments(status = 'all', limit = 10) {
        try {
            const response = await fetch(`${this.apiBase}/get-shared-appointments?status=${status}&limit=${limit}&student_id=${this.studentId}&therapist_id=${this.therapistId}`);
            const data = await response.json();
            
            if (data.appointments) {
                return data;
            } else {
                throw new Error(data.error || 'Failed to load appointments');
            }
            
        } catch (error) {
            console.error('Failed to load appointments:', error);
            return { appointments: [], total_count: 0 };
        }
    }
    
    handleAppointmentUpdate(data) {
        console.log('Appointment updated:', data);
        
        // Show notification
        const actionMap = {
            'confirm': 'confirmed',
            'reschedule': 'rescheduled',
            'cancel': 'cancelled',
            'complete': 'completed'
        };
        
        const actionText = actionMap[data.action] || data.action;
        this.showNotification(`Appointment ${actionText}`, 'success');
        
        // Emit event for custom handlers
        this.emit('appointment_updated', data);
    }
    
    // === RESOURCES ===
    
    async shareResource(resourceId, message = '') {
        try {
            const response = await fetch(`${this.apiBase}/share-resource`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    student_id: this.studentId,
                    therapist_id: this.therapistId,
                    resource_id: resourceId,
                    message: message
                })
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.showNotification('Resource shared successfully', 'success');
                this.emit('resource_shared', data);
                return data;
            } else {
                throw new Error(data.error || 'Failed to share resource');
            }
            
        } catch (error) {
            console.error('Failed to share resource:', error);
            this.showNotification('Failed to share resource', 'error');
            throw error;
        }
    }
    
    async loadSharedResources(limit = 20) {
        try {
            const response = await fetch(`${this.apiBase}/get-shared-resources?limit=${limit}&student_id=${this.studentId}&therapist_id=${this.therapistId}`);
            const data = await response.json();
            
            if (data.shared_resources) {
                return data;
            } else {
                throw new Error(data.error || 'Failed to load shared resources');
            }
            
        } catch (error) {
            console.error('Failed to load shared resources:', error);
            return { shared_resources: [], total_count: 0 };
        }
    }
    
    handleResourceShared(data) {
        console.log('Resource shared:', data);
        
        this.showNotification(`Resource shared: ${data.title}`, 'success');
        this.emit('resource_shared', data);
    }
    
    // === NOTIFICATIONS ===
    
    async loadNotifications(limit = 10, unreadOnly = false) {
        try {
            const response = await fetch(`${this.apiBase}/get-notifications?limit=${limit}&unread_only=${unreadOnly}`);
            const data = await response.json();
            
            if (data.notifications) {
                return data;
            } else {
                throw new Error(data.error || 'Failed to load notifications');
            }
            
        } catch (error) {
            console.error('Failed to load notifications:', error);
            return { notifications: [], unread_count: 0, total_count: 0 };
        }
    }
    
    async markNotificationRead(notificationId) {
        try {
            const response = await fetch(`${this.apiBase}/mark-notification-read/${notificationId}`, {
                method: 'POST'
            });
            
            const data = await response.json();
            
            if (!data.success) {
                throw new Error(data.error || 'Failed to mark notification as read');
            }
            
            return data;
            
        } catch (error) {
            console.error('Failed to mark notification as read:', error);
        }
    }
    
    showNotification(message, type = 'info', duration = 5000) {
        if (!this.notificationContainer) return;
        
        const notification = document.createElement('div');
        notification.className = `connection-notification ${type}`;
        
        notification.innerHTML = `
            <div class="flex items-start">
                <div class="flex-1">
                    <p class="text-sm font-medium text-gray-900">${this.escapeHtml(message)}</p>
                    <p class="text-xs text-gray-500">${new Date().toLocaleTimeString()}</p>
                </div>
                <button class="ml-2 text-gray-400 hover:text-gray-600" onclick="this.parentElement.parentElement.remove()">
                    <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"></path>
                    </svg>
                </button>
            </div>
        `;
        
        this.notificationContainer.appendChild(notification);
        
        // Animate in
        setTimeout(() => {
            notification.classList.add('show');
        }, 100);
        
        // Auto remove
        if (duration > 0) {
            setTimeout(() => {
                notification.classList.remove('show');
                setTimeout(() => {
                    if (notification.parentElement) {
                        notification.remove();
                    }
                }, 300);
            }, duration);
        }
    }
    
    // === STATUS ===
    
    async updateConnectionStatus() {
        try {
            const response = await fetch(`${this.apiBase}/get-connection-status?student_id=${this.studentId}&therapist_id=${this.therapistId}`);
            const data = await response.json();
            
            if (data.connection_active !== undefined) {
                this.updateStatusIndicator(data.connection_active);
                this.emit('connection_status', data);
                return data;
            } else {
                throw new Error(data.error || 'Failed to get connection status');
            }
            
        } catch (error) {
            console.error('Failed to update connection status:', error);
            this.updateStatusIndicator(false);
            return null;
        }
    }
    
    updateStatusIndicator(connected) {
        if (!this.statusIndicator) return;
        
        const statusClass = connected ? 'connected' : 'disconnected';
        const statusText = connected ? 'Connected' : 'Disconnected';
        
        this.statusIndicator.innerHTML = `
            <div class="connection-status-indicator ${statusClass}">
                <div class="connection-pulse ${statusClass}"></div>
                <span>${statusText}</span>
            </div>
        `;
    }
    
    // === UTILITY METHODS ===
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    formatTime(timestamp) {
        return new Date(timestamp).toLocaleString();
    }
    
    // === EVENT SYSTEM ===
    
    on(event, handler) {
        if (this.eventHandlers[event]) {
            this.eventHandlers[event].push(handler);
        }
    }
    
    off(event, handler) {
        if (this.eventHandlers[event]) {
            const index = this.eventHandlers[event].indexOf(handler);
            if (index > -1) {
                this.eventHandlers[event].splice(index, 1);
            }
        }
    }
    
    emit(event, data) {
        if (this.eventHandlers[event]) {
            this.eventHandlers[event].forEach(handler => {
                try {
                    handler(data);
                } catch (error) {
                    console.error(`Error in event handler for ${event}:`, error);
                }
            });
        }
    }
    
    // === CLEANUP ===
    
    destroy() {
        if (this.socket) {
            this.socket.disconnect();
        }
        
        if (this.notificationContainer) {
            this.notificationContainer.remove();
        }
        
        // Clear event handlers
        Object.keys(this.eventHandlers).forEach(event => {
            this.eventHandlers[event] = [];
        });
        
        console.log('Connection Manager destroyed');
    }
}

// === UTILITY FUNCTIONS ===

// Auto-initialize if configuration is found
document.addEventListener('DOMContentLoaded', function() {
    const config = window.connectionConfig;
    if (config) {
        window.connectionManager = new ConnectionManager(config);
    }
});

// Global helper functions
window.ConnectionHelpers = {
    // Quick message sending
    sendQuickMessage: async function(message) {
        if (window.connectionManager) {
            return await window.connectionManager.sendMessage(message);
        }
        throw new Error('Connection Manager not initialized');
    },
    
    // Quick appointment actions
    confirmAppointment: async function(appointmentId) {
        if (window.connectionManager) {
            return await window.connectionManager.syncAppointment(appointmentId, 'confirm');
        }
        throw new Error('Connection Manager not initialized');
    },
    
    rescheduleAppointment: async function(appointmentId, newDateTime) {
        if (window.connectionManager) {
            return await window.connectionManager.syncAppointment(appointmentId, 'reschedule', {
                new_datetime: newDateTime
            });
        }
        throw new Error('Connection Manager not initialized');
    },
    
    cancelAppointment: async function(appointmentId, reason = 'Cancelled') {
        if (window.connectionManager) {
            return await window.connectionManager.syncAppointment(appointmentId, 'cancel', {
                reason: reason
            });
        }
        throw new Error('Connection Manager not initialized');
    },
    
    // Load and display messages in a container
    loadMessagesIntoContainer: async function(containerId, limit = 50) {
        if (!window.connectionManager) {
            throw new Error('Connection Manager not initialized');
        }
        
        const container = document.getElementById(containerId);
        if (!container) {
            throw new Error(`Container ${containerId} not found`);
        }
        
        try {
            const data = await window.connectionManager.loadMessages(limit);
            
            container.innerHTML = '';
            
            data.messages.forEach(message => {
                const messageEl = document.createElement('div');
                messageEl.className = `message ${message.sender === window.connectionManager.userRole ? 'sent' : 'received'}`;
                
                messageEl.innerHTML = `
                    <div class="message-content">
                        <p>${window.connectionManager.escapeHtml(message.content)}</p>
                        <small class="message-time">${message.formatted_time}</small>
                    </div>
                `;
                
                container.appendChild(messageEl);
            });
            
            container.scrollTop = container.scrollHeight;
            
        } catch (error) {
            console.error('Failed to load messages:', error);
            container.innerHTML = '<p class="text-red-500">Failed to load messages</p>';
        }
    },
    
    // Initialize connection manager with custom config
    init: function(config) {
        if (window.connectionManager) {
            window.connectionManager.destroy();
        }
        window.connectionManager = new ConnectionManager(config);
        return window.connectionManager;
    }
};

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ConnectionManager;
}