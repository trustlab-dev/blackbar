export interface User {
  id: string;
  email: string;
  name?: string;
  role: string;
  created_at: string;
  updated_at: string;
}

export interface UserCreateRequest {
  email: string;
  password: string;
  name?: string;
  role?: string;
}

export interface UserUpdateRequest {
  email?: string;
  password?: string;
  name?: string;
  role?: string;
}
