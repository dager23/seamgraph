// Frontend API client with fetch calls
const API_BASE = process.env.REACT_APP_API_URL;
const DEBUG = process.env.REACT_APP_DEBUG;

export async function getUser(userId) {
  const res = await fetch(`/api/v1/users/${userId}`);
  return res.json();
}

export async function createUser(data) {
  const res = await fetch('/api/v1/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return res.json();
}

export async function deleteUser(userId) {
  const res = await fetch(`/api/v1/users/${userId}`, {
    method: 'DELETE',
  });
  return res.json();
}

export async function healthCheck() {
  const res = await fetch('/health');
  return res.json();
}

// This route does NOT exist in the backend — orphan!
export async function getSettings() {
  const res = await fetch('/api/v1/settings');
  return res.json();
}
