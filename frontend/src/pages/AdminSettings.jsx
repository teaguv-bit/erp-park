import { PageHeader } from "../ui";
import AdminUsers from "./AdminUsers";

export default function AdminSettings() {
  return (
    <div className="adminSettingsShell">
      <PageHeader crumb="Sistema" title="Administração" />
      <AdminUsers />
    </div>
  );
}
