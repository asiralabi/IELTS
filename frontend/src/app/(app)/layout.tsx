import { Sidebar, MobileNav } from "@/components/shell/sidebar";
import { AiAssistant } from "@/components/shell/ai-assistant";
import { AuthGuard } from "@/components/shell/auth-guard";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <div className="relative min-h-screen bg-mesh">
        <Sidebar />
        <MobileNav />
        <div className="px-4 pb-28 pt-6 sm:px-8 md:ml-[100px] md:pb-10 lg:pr-12">
          {children}
        </div>
        <AiAssistant />
      </div>
    </AuthGuard>
  );
}
