import api from '../api/client';

// Define User interface here to prevent import issues
interface User {
  id: string;
  email: string;
  name?: string;
  role: string;
  created_at: string;
  updated_at: string;
}

// Get all users
export const getUsers = async () => {
  const response = await api.get('/auth/users');
  return response.data;
};

// Get a specific user by ID
export const getUserById = async (userId: string) => {
  const response = await api.get(`/auth/users/${userId}`);
  return response.data as User;
};

// Create a new user (admin only)
export const createUser = async (userData: any) => {
  const response = await api.post('/auth/users', userData);
  return response.data;
};

// Update an existing user
export const updateUser = async (userId: string, userData: any) => {
  const response = await api.put(`/auth/users/${userId}`, userData);
  return response.data;
};

// Delete a user (admin only)
export const deleteUser = async (userId: string) => {
  const response = await api.delete(`/auth/users/${userId}`);
  return response.data;
};
