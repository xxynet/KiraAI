/**
 * Unified API call function with JWT authentication
 */
async function apiCall(url, options = {}) {
    const jwtToken = localStorage.getItem('jwt_token');

    if (!jwtToken) {
        window.location.href = '/login';
        throw new Error('No JWT token found');
    }

    const headers = {
        ...options.headers
    };

    if (!(options.body instanceof FormData) && !headers['Content-Type']) {
        headers['Content-Type'] = 'application/json';
    }

    headers['Authorization'] = `Bearer ${jwtToken}`;

    const response = await fetch(url, {
        ...options,
        headers
    });

    // Handle 401 Unauthorized
    if (response.status === 401) {
        localStorage.removeItem('jwt_token');
        window.location.href = '/login';
        throw new Error('Unauthorized');
    }

    return response;
}
