1. graphical nodes
  1. all the basic plots
  2. all the basic graphs
2. add notification node
   1. smtp
   2. telegram
3. AI API support node
   1. ollama
   2. openai
4. add suport to directly ingest another analysis tab as source (should already be a lazyframe in the backend included with the export)
5. add healthecks (send notification)
   1. on successfull full builds
   2. column rules
   3. row count
6. data lineage tab
   1. used for visualisation of datasources
   2. datsource lineage (if one is derived from another bacause it was generated with analysis)
   3. graphical UI
   4. used for scheduling.
      1. cron schedules with DAGs for sequential builds of dependent datasets
      2. should use the backed analysis to build the datasets with correct logic
7. preview of running build
   1. since some builds might take longer would be nice to see the execution time and such in graphical way..
   2. spark has special ui for stages and such not sure what does polars have either way visualisating schedules and their builds is nice to have as we see what is building for how long and what will be built after
8. builds UI improvements
   1. as mentioned before some more graphics and relations
   2. better filters
9. column stats in datasources
   1.  when clicking on column we should trigger a column stats compute..
   2.  it should come from the bottom
   3.  have all the related stats for column of type.
   4.  think polars has some exact thing that will do it automaticaly
   5.  this should be displayed in pretty manner
10. the indexeddb popup 
    1.  should have truncated rows to fixed size
    2.  expand on click
    3.  have a copy button
11. we need an analysis version history
    1.  with ui for selecting the version we want
    2.  should be saved in backend with unlimited retentions
    3.  each hit of save button should append a new analysis version that will be backed.
    4.  the mode selet will have a third button and that is rollback which will show a full big popup in the middle of the screen with the past version to choose from
    5.  reverting to version is just another append to the version history 