# State Fair Bus Report: 2025

Did you enjoy the 2025 Great New York State Fair? We did. We saw En Vogue perform "Whatta Man" on the same stage where we saw Salt N' Pepa perform "Whatta Man" two years ago. We watched other people eat the Pebble Pop. We thought the Dubai cream puff in the Dairy Building was not really worth the hype, but the regular vanilla one was solid.

This report is mostly the same as [../state_fair_2024](our report on 2024) and that page has more detail on what we did and how.

One big caveat is that we had data outages twice during the State Fair, on the mornings of August 30 and September 1. For those days you won't see any bus data before 11 AM Eastern.

Here is a list of all the State Fair bus trips we identified.

{% include 2025/dataframe_export.html %}

We also have [https://github.com/markongithub/clever_buses_py/blob/main/output/trips_2025.csv](that same list in CSV format).

So what did that mean for the rider? Here's a graph of how much time elapsed between trips for each route and direction. In this and all the other graphs, you can click on the route labels to include or exclude particular routes. You can also zoom in on a particular time period and then double-click to zoom out.

{% include 2025/plotly_export.html %}

Here we see a lot of really good service, but also a lot of times where people had to wait 30 minutes or more.

Here are the median wait times by day and route:

{% include 2025/median_wait_times.html %}

And also the 90th percentile wait times by day, which tell you what your wait would have been like if your luck was bad:

{% include 2025/90p_wait_times.html %}

New this year, here are the numbers of buses per route that were reporting their locations at any given time. Just for fun I threw in the Orange Lot shuttles for all you motorists. You can see that there are generally more buses on the Destiny route than any other.

{% include 2025/bus_counts.html %}

On the second Sunday of the fair, at the start of the aforementioned En Vogue concert, the fair posted this notice on Facebook:

![a Facebook post by the official New York State Fair account warning that parking lots are full and recommending the bus](/assets/2025/facebook_lots_full.png)

We can zoom in on that time in our graph and see how the buses were doing. Let's only look at Fairgrounds-bound buses for now:

![wait times for Fairgrounds-bound buses around 6 PM Eastern on August 31, 2025](/assets/2025/wait_times_20250831_6PM.png)

The Destiny buses look solid but there was a full half-hour wait at the downtown hub. Looking at the "bus counts" graph, we see that there were only two buses running the downtown hub route at the time. That's a clear opportunity for improvement in service.

That's the report! We think it demonstrates a valuable service with room for improvement. [https://github.com/markongithub/clever_buses_py/blob/main/output/](Most of our findings are in CSV format) so play with the data yourself and let us know what else you find.

See you next year at the Fair!