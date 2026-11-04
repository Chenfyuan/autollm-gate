import { RequestLogs } from "@/components/request-logs";
export function AdminLogs() {
  return <RequestLogs base="/api/admin/logs" admin loginPath="/admin/login" />;
}
