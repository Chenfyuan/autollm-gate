import { RequestLogs } from "@/components/request-logs";
export function ConsoleLogs() {
  return <RequestLogs base="/api/console/logs" loginPath="/login" />;
}
