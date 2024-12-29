Centro provides [bus service to the Great New York State Fair](https://www.centro.org/service_schedules/ny-state-fair) from three locations around Onondaga County: the Centro hub in downtown Syracuse, Destiny USA, and Long Branch Park. Their site provides start and end times for the service, but no specific timetable or promises of frequency.

Real-time arrival information for the buses is available on [Centro's Bus Time site](https://bus-time.centro.org/bustime/eta/eta.jsp?agency=All&route=SY901&direction=LOOP&stop=Hub%20Warren%20St&id=18106&showAllBusses=on). We scraped that site during the state fair. Any buses that weren't showing their locations on bus-time aren't included in this data, but I'll discuss that below under "How we did it".

# What we learned

Here is a list of all the State Fair trips we identified.

{% include dataframe_export.html %}

All told, it looks like a total of 4925 completed one-way trips throughout the state fair, for an average of 379 per day. Grouping by route, the numbers look like

```
901 State Fair - Hub    1328
907 Long Branch Park    1279
909 Destiny USA         2317
```

It makes sense that Destiny would have the most because it's the shortest route and, when I-690 is moving normally, the most direct.

But as a passenger you don't really care about the raw number of trips. You care about how long you had to wait, and how long the trip took. So here is a graph of wait times for each route and direction. (Skip further down to see how this was calculated.)

In this and all the other graphs, you can click on the route labels to include or exclude particular routes.

{% include plotly_export.html %}

For example, the afternoon of August 27 I went to Destiny USA to get the 909 bus to the fair, in anticipation of the Blue Öyster Cult show.  A huge crowd of people was already waiting in the hot sun. Sure enough, when I zoom in on the afternoon of August 27 on that graph, I see exactly what I expected - a 37 minute gap between 3:58 and 4:35 PM. That's not great.

(All those Blue Öyster Cult fans may not have been [burning for you](https://www.youtube.com/watch?v=kn-8n4QKUS4), but they were certainly burning. [They had a fever](https://www.youtube.com/watch?v=cVsQLlk-T0s), and the only prescription was more bus service. Perhaps [Godzilla](https://www.youtube.com/watch?v=myqSETD5_bs) picked up a bus and threw it back down.)

So let's look at the median wait times for every route for every day of the fair. If you showed up at the stop at a random time, this is about how long you could expect to wait for your bus:

{% include median_wait_times.html %}

Not bad! It looks like there was some trouble on the first day but overall you could expect to wait around 12 minutes. But maybe looking at the median is concealing some bad delays. Let's look at the 90th percentile. You had a 90% chance of catching a bus with this wait or better:

{% include 90p_wait_times.html %}

Now we see the delays a bit more clearly. But still, this is a pretty decent level of service.

# How we did it

As we said above, we started by scraping data from `bus-time.centro.org`. But that isn't nearly enough.

Some transit agencies release data tagged with a trip ID you can correlate against a [GTFS](https://en.wikipedia.org/wiki/GTFS) timetable. Centro doesn't. It just releases a list of buses with their positions and a few other pieces of data. The really useful field is the headsign, which is something like "909 Destiny USA". However, even the 909 Destiny USA buses don't always have that set. Sometimes it changes to "N/A" and back again. It also doesn't say whether it's going to Destiny or to the fairgrounds. We have to guess all that.

So we [go through every bus's position](https://github.com/markongithub/clever_buses_py/blob/main/state_fair_report.py) and look for State Fair buses. Then we watch for when a bus goes near one terminal, and wait for it to go near the other. When it's done both, we call that a completed trip. This is a very flawed system because the driver could have taken a break and left the bus parked for 20 minutes during that "trip".

The biggest flaw in all of this is that the bus might not be sharing its GPS data at all, or it might have the headsign listed wrong. In that case, it won't show up at all in this report. So consider this report to err on the side of pessimism.

Once we have all the trips, which we've uploaded here in CSV, we can figure out [how long you'd have to wait](https://github.com/markongithub/clever_buses_py/blob/main/calculate_wait_times.py) from every minute that the buses were operating.
