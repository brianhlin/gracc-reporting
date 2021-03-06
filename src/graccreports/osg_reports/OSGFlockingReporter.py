import datetime
import traceback
import sys
from collections import defaultdict

from elasticsearch_dsl import Search

from . import Reporter, runerror, get_configfile, get_template

logfile = 'osgflockingreport.log'
default_templatefile = 'template_flocking.html'
MAXINT = 2**31 - 1


# Helper functions

@Reporter.init_reporter_parser
def parse_opts(parser):
    """
    Don't need to add any options to Reporter.parse_opts
    """
    pass


class FlockingReport(Reporter):
    """Class to hold information for and to run OSG Flocking report

    :param str config: Report Configuration filename
    :param str start: Start time of report range
    :param str end: End time of report range
    :param str template: Filename of HTML template to generate report
    :param bool verbose: Verbose flag
    :param bool is_test: Whether or not this is a test run.
    :param bool no_email: If true, don't actually send the email
    """
    def __init__(self, config, start, end, template=False, verbose=False,
                 is_test=False, no_email=False, ov_logfile=None):
        report = 'Flocking'

        if ov_logfile:
            rlogfile = ov_logfile
            logfile_override = True
        else:
            rlogfile = logfile
            logfile_override = False

        self.title = "OSG Flocking: Usage of OSG Sites for {0} - {1}".format(start, end)

        super(FlockingReport, self).__init__(report, config, start, end=end,
                                             template=template, verbose=verbose,
                                             no_email=no_email, is_test=is_test,
                                             logfile=rlogfile,
                                             logfile_override=logfile_override)

        self.verbose = verbose
        self.no_email = no_email
        self.is_test = is_test
        self.header = ["VOName", "SiteName", "ProbeName", "ProjectName",
                       "Wall Hours"]

    def run_report(self):
        """Higher level method to handle the process flow of the report
        being run"""
        self.send_report()

    def query(self):
        """Method to query Elasticsearch cluster for Flocking Report
        information

        :return elasticsearch_dsl.Search: Search object containing ES query
        """
        # Gather parameters, format them for the query
        starttimeq = self.start_time.isoformat()
        endtimeq = self.end_time.isoformat()

        if self.verbose:
            self.logger.info(self.indexpattern)

        probeslist = self.config[self.report_type.lower()]['probe_list']

        # Elasticsearch query and aggregations
        s = Search(using=self.client, index=self.indexpattern) \
                .filter("range", EndTime={"gte": starttimeq, "lt": endtimeq}) \
                .filter("terms", ProbeName=probeslist)\
                .filter("term", ResourceType="Payload")[0:0]
        # Size 0 to return only aggregations

        # Bucket aggs
        Bucket = s.aggs.bucket('group_Site', 'terms', field='SiteName', size=MAXINT) \
            .bucket('group_VOName', 'terms', field='ReportableVOName', size=MAXINT) \
            .bucket('group_ProbeName', 'terms', field='ProbeName', size=MAXINT) \
            .bucket('group_ProjectName', 'terms', field='ProjectName', missing='N/A', size=MAXINT)

        # Metric aggs
        Bucket.metric("CoreHours_sum", "sum", field="CoreHours")

        return s

    def generate(self):
        """Higher-level generator method that calls the lower-level functions
        to generate the raw data for this report.

        Yields rows of raw data
        """
        results = self.run_query()

        # Iterate through the buckets to get our data, yield it
        for site in results.group_Site.buckets:
            sitekey = site.key
            for vo in site.group_VOName.buckets:
                vokey = vo.key
                for probe in vo.group_ProbeName.buckets:
                    probekey = probe.key
                    projects = (project for project in probe.group_ProjectName.buckets)
                    for project in projects:
                        yield (sitekey, vokey, probekey, project.key, project.CoreHours_sum.value)

    def format_report(self):
        """Report formatter.  Returns a dictionary called report containing the
        columns of the report.

        :return dict: Constructed dict of report information for
        Reporter.send_report to send report from"""
        report = defaultdict(list)

        for result_tuple in self.generate():
            if self.verbose:
                print "{0}\t{1}\t{2}\t{3}\t{4}".format(*result_tuple)

            mapdict = dict(zip(self.header, result_tuple))
            for key, item in mapdict.iteritems():
                report[key].append(item)

        tot = sum(report['Wall Hours'])
        for col in self.header:
            if col == 'VOName':
                report[col].append('Total')
            elif col == 'Wall Hours':
                report[col].append(tot)
            else:
                report[col].append('')

        if self.verbose:
            print "The total Wall hours in this report are {0}".format(tot)

        return report


def main():
    args = parse_opts()

    # Set up the configuration
    config = get_configfile(override=args.config)

    templatefile = get_template(override=args.template, deffile=default_templatefile)

    try:
        # Create an FlockingReport object, and run the report
        f = FlockingReport(config,
                           args.start,
                           args.end,
                           verbose=args.verbose,
                           is_test=args.is_test,
                           no_email=args.no_email,
                           template=templatefile,
                           ov_logfile=args.logfile)
        f.run_report()
        print "OSG Flocking Report execution successful"
    except Exception as e:
        errstring = '{0}: Error running OSG Flocking Report. ' \
                    '{1}'.format(datetime.datetime.now(), traceback.format_exc())
        runerror(config, e, errstring, logfile)
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    main()

