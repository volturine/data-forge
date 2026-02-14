original taskfile:

1. graphical nodes
1. all the basic plots
1. all the basic graphs
1. add notification node
   1. notification configs should be configurable all in one in the nodes
      1. smtp
      2. telegram
1. AI API support node ollama/openai
   1. custom API endpoints
   2. configurable to wire localhosted or prod endpoints
1. add suport to directly ingest another analysis/id/ tab as source
   1. each analysis/id tab should have last node pose two functions export as datasource and second is point to the output lazyframe in the engine
   2. withing same analysis/id/ one should be able to use any tab as an input
   3. only withing the same analysis/id because we want to directly use the lazyframe
   4. when in different analysis we are still dependend to use Datasource witch can be only updated manualy from the analysis or by schedule
   5. basicaly this add same behaviour as python files.. each analysis id is a python file with transformation
      1. within same python file for optimal performance we use direct lazy frame
      2. between python files we are dependent on what was build and when it was build and if we want fresh data we need to schedule back to back builds
1. add healthecks (send notification)
   1. lives in datasources config panel
   2. on successfull full builds
   3. column rules
   4. row count
1. data lineage tab
   1. used for visualisation of datasources
   2. datsource lineage (if one is derived from another bacause it was generated with analysis)
   3. graphical UI with dragable nodes of all datasrouces and their relations.
   4. used for scheduling.
      1. cron schedules with DAGs for sequential builds of dependent datasets
      2. should use the backed analysis to build the datasets with correct logic
1. preview of running build
   1. since some builds might take longer would be nice to see the execution time and such in graphical way..
   2. spark has special ui for stages and such not sure what does polars have either way visualisating schedules and their builds is nice to have as we see what is building for how long and what will be built after
1. builds UI improvements
   1. as mentioned before some more graphics and relations
   2. better filters
1. column stats in datasources
1. when clicking on column we should trigger a column stats compute..
1. it should come from the bottom
1. have all the related stats for column of type.
1. think polars has some exact thing that will do it automaticaly
1. this should be displayed in pretty manner
1. the indexeddb popup
   1. should have truncated rows to fixed size
   2. expand on click
   3. have a copy button
1. we need an analysis version history
   1. with ui for selecting the version we want
   2. should be saved in backend with unlimited retentions
   3. each hit of save button should append a new analysis version that will be backed.
   4. the mode selet button in analysis
      1. will have a third button, that is rollback
      2. it will show a full big popup in the middle of the screen with the past version to choose from
   5. reverting to version is just another append to the version history


---
found bugs and further specificaitons for allignemnt
main point dont stop until you have tested these with python tests for all backend.. and verified frontend does make equvalient calls and all datatypes are correct


1. SMTP and Telegram settings are configured via environment variables and cannot be changed here. should be configurable inside the frontend.. but can be prepopulaated with env variables
2. the lineage tab has broken physics and is ever expanding.
    1. i would say it should take up most of the screen
    2. i would like it to be that the schedules ui would be available as common component
        1. in datasource config pannel
        2. analysis/id/ in the datasource node as expanding view
        3. in its own schedules page
        4. in datalineage as panel
    3. it also has the links graphicali in wrong place not even attached to the nodes
3. when i create a derived analysis from a tab it say there are no nodes..
    1. it shoulp populate the datasource node and export node straing away not wait for me to add some node so that the two fixed node can appear
4. graph nodes are still not treated as only visualisation nodes for the incomings data
    1. they should not affect the data comming in/out.. same way inline table does not affect data
    2. it should only take input data and visualize it into the desired graph
    3. use https://datavisualizationwithsvelte.com/
    4. it takes data in, visualizes it, and lets the dag work as if its not there. same as inlinepreviewnode
    5. i still cant put chart to any place i want
    6. where are the prety graphs?? only thing i see when i add graphs is some string saying what should be actualy visualized
    7. what i ment as leafs they act exactly like inline dataset previews they dont modify the DAG can be wherever..
    8. they react to data
    9. visualize it in inline node
    10. maybe use some visualisation library for the diferent graphs standard one best for svelte that we could use even when hosting with fastapi..
        1. d3 for example https://datavisualizationwithsvelte.com/
    11. they can be wherever in thed dag
5. i see that as soon as i ingest analysis/id tab as input for another tab
    1. a new datasource is added.. i hope this is not used as the source for the second analysis tab and is only for other logic
    2. in the second analysis tab i only want to rely on the lazyframe
    3. but i understan that for the visualisation purposes, healthchecks and schedules it does need a representation elsewhere
    4. so it may be correct as is but it need to be verified
6. i see step execution timeline
    1. i have no idea what these id's mean there
    2. its just id and the execution time but the id tels me nothing realy.
    3. therefore it needs improvements for this ui to be usefull
7. schedule is doing god knows what
    1. schedule is saing its executing analysis
    2. i dont see the build logged in the ui of build nor the asociated datasets
    3. added export of datasource from an analysis and a schedule but i dont see in timetravelui new snapshots so it means that actual build has not run
    4. adding to chedule longer named analysis will make the chedule rows 2 line high. breaking the ui.. truncate the name.
        1. make the rows expandable with editing of schedule possible
    5. i see that builds says schedule was executed and data exported but thats no the case as timetravelui does not show it
    6. also som analysis that first were no real datasource out and were scheduled seem to do nothing on schedule execution not even end up in builds
    7. build detail ui should show if something was executed from schedule
    8. also any analysis should be exacutable even if there is no output datasource... as they can be for notification purposes.. but im not sure why when i first scheduled a analysis without output it didnt execute at all even after i aded the exports.
8. lets add option to directly download a datasource from the datasources ui
9. let me rename analysis version title
    1. basicaly allowing me to distinguis different versions
10. builds ui should include the ouput of build as column also
11. healthchecks tab should show how many healthcheks are active
    1. their status past few exports
12. lets add a global configuration for the notification base settings
    1. these can be used as default in the notification node
    2. should be a small button in line where we have engines/cache/theme/settings
    3. it will have the base smtp and telegram settings i can configure/test
    4. it can have the configuration on whether to hide/unhide indexdb cache button
    5. it should be a popup in the middle of the screen
13. lets allign on the ai handler.. it should be nothing more than wrapper to call llm chat apis with inputs from the row/columns on polars
    1. basicaly its a udf with column input/inputs and then calling the ai endpoint with promt being either the input or literal
    2. output from the ai is a result column
    3. basicaly ai node is just custom predefined udf node with wiring to llm requests
    4. also update the agents.md if there is mention of this.
14. agents.md should reflect our general ideas and standards
    1. if you fix something after yourself implemented it for the first time and its just mismatched proper usage of standards for example as using Map instead of sveltemap that should be used.. always update your findings in agents.md so that we dont have to fix things rather implement correctly from the get go..
    2. also add this self evolving behaviour as a rule in agents.md
