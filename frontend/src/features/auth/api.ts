import { apiClient } from "@/lib/api-client";
import type { AuthUser } from "@/stores/authStore";

export interface AccessTokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: AuthUser;
}

export function registerAccount(payload: { email: string; password: string; full_name: string }) {
  return apiClient.post<AccessTokenResponse>("/auth/register", payload);
}

export function login(payload: { email: string; password: string }) {
  return apiClient.post<AccessTokenResponse>("/auth/login", payload);
}

export function refreshSession() {
  return apiClient.post<AccessTokenResponse>("/auth/refresh");
}

export function logout() {
  return apiClient.post<void>("/auth/logout");
}

export function forgotPassword(payload: { email: string }) {
  return apiClient.post<void>("/auth/forgot-password", payload);
}

export function resetPassword(payload: { token: string; new_password: string }) {
  return apiClient.post<void>("/auth/reset-password", payload);
}

export function fetchMe() {
  return apiClient.get<AuthUser>("/users/me");
}

export function updateProfile(payload: { full_name: string }) {
  return apiClient.patch<AuthUser>("/users/me", payload);
}

export function changePassword(payload: { current_password: string; new_password: string }) {
  return apiClient.post<void>("/users/me/change-password", payload);
}

export function deleteAccount(payload: { password: string }) {
  return apiClient.delete<void>("/users/me", payload);
}
