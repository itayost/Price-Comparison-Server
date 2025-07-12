import { Suspense } from 'react';
import { Card } from '@/components/ui/card';
import { KitchenDashboard } from '@/components/kitchen/kitchen-dashboard';
import { getOrdersForToday } from '@/lib/actions/orders';
import { Loader2 } from 'lucide-react';

export const metadata = {
  title: "Kitchen - Today's Orders",
  description: "Manage today's orders for cooking and delivery",
};

export default async function KitchenPage() {
  const todayOrders = await getOrdersForToday();

  return (
    <div className="h-full bg-gray-50 p-4">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-3xl font-bold mb-6">
          Kitchen Dashboard -{' '}
          {new Date().toLocaleDateString('en-US', {
            weekday: 'long',
            year: 'numeric',
            month: 'long',
            day: 'numeric',
          })}
        </h1>

        <Suspense
          fallback={
            <Card className="p-8 flex items-center justify-center">
              <Loader2 className="h-8 w-8 animate-spin mr-2" />
              <span>Loading today's orders...</span>
            </Card>
          }
        >
          <KitchenDashboard orders={todayOrders} />
        </Suspense>
      </div>
    </div>
  );
}
