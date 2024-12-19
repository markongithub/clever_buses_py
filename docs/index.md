The New York State Fair. Pardon me. [The GREAT New York State Fair](https://nysfair.ny.gov/). It's great.

Centro provides [bus service to the fair](https://www.centro.org/service_schedules/ny-state-fair) from three locations around Onondaga County: the Centro hub in downtown Syracuse, Destiny USA, and Long Branch Park. Their site provides start and end times for the service, but no specific timetable or promises of frequency.

Real-time arrival information for the buses is available on [Centro's Bus Time site](https://bus-time.centro.org/bustime/eta/eta.jsp?agency=All&route=SY901&direction=LOOP&stop=Hub%20Warren%20St&id=18106&showAllBusses=on). I scraped that site during the state fair.

# What I learned

Here is a list of all the State Fair trips I identified.

{% include dataframe_export.html %}

All told, it looks like a total of 4925 completed one-way trips throughout the state fair, for an average of 379 per day. Grouping by route, the numbers look like

```
901 State Fair - Hub    1328
907 Long Branch Park    1279
909 Destiny USA         2317
```

It makes sense that Destiny would have the most because it's the shortest route and, when I-690 is moving normally, the most direct.

But as a passenger you don't really care about the raw number of trips. You care about how long you had to wait, and how long the trip took. So here is a graph of wait times for each route and direction.

{% include plotly_export.html %}

On the afternoon of August 27 I went to Destiny USA to get the 909 bus to the fair, in anticipation of the Blue Öyster Cult show.  A huge crowd of people was already waiting in the hot sun. Sure enough, when I zoom in on the afternoon of August 27 on that graph, I see exactly what I expected - a 37 minute gap between 3:58 and 4:35 PM. That's not great.

All those Blue Öyster Cult fans may not have been [burning for you](https://www.youtube.com/watch?v=kn-8n4QKUS4), but they were certainly burning. [They had a fever](https://www.youtube.com/watch?v=cVsQLlk-T0s), and the only prescription was more bus service. Perhaps [Godzilla](https://www.youtube.com/watch?v=myqSETD5_bs) picked up a bus and threw it back down.

# Methodology
