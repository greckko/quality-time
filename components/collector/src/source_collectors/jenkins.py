"""Jenkins metric collector."""

from datetime import datetime, timedelta
from typing import cast, Iterator, List

import requests

from utilities.type import Job, Jobs, Entities, URL, Value
from .source_collector import SourceCollector


class JenkinsJobs(SourceCollector):
    """Collector to get job counts from Jenkins."""

    def _api_url(self) -> URL:
        url = super()._api_url()
        job_attrs = "buildable,color,url,name,builds[result,timestamp]"
        return URL(f"{url}/api/json?tree=jobs[{job_attrs},jobs[{job_attrs},jobs[{job_attrs}]]]")

    def _parse_source_responses_value(self, responses: List[requests.Response]) -> Value:
        return str(len(list(self.__jobs(responses[0].json()["jobs"]))))

    def _parse_source_responses_entities(self, responses: List[requests.Response]) -> Entities:
        return [
            dict(
                key=job["name"], name=job["name"], url=job["url"], build_status=self._build_status(job),
                build_age=str(self._build_age(job).days) if self._build_age(job) < timedelta.max else "",
                build_date=str(self.__build_datetime(job).date()) if self.__build_datetime(job) > datetime.min else "")
            for job in self.__jobs(responses[0].json()["jobs"])]

    def __jobs(self, jobs: Jobs) -> Iterator[Job]:
        """Recursively return the jobs and their child jobs that need to be counted for the metric."""
        for job in jobs:
            if job.get("buildable") and self._count_job(job):
                yield job
            for child_job in self.__jobs(job.get("jobs", [])):
                yield child_job

    def _count_job(self, job: Job) -> bool:
        """Return whether the job should be counted."""
        raise NotImplementedError  # pragma: nocover

    def _build_age(self, job: Job) -> timedelta:
        """Return the age of the most recent build of the job."""
        build_datetime = self.__build_datetime(job)
        return datetime.now() - build_datetime if build_datetime > datetime.min else timedelta.max

    @staticmethod
    def __build_datetime(job: Job) -> datetime:
        """Return the date and time of the most recent build of the job."""
        builds = job.get("builds")
        return datetime.utcfromtimestamp(int(builds[0]["timestamp"]) / 1000.) if builds else datetime.min

    @staticmethod
    def _build_status(job: Job) -> str:
        """Return the build status of the job."""
        builds = job.get("builds")
        if builds:
            status = builds[0].get("result")
            if status:
                return status.capitalize().replace("_", " ")
        return "Not built"


class JenkinsFailedJobs(JenkinsJobs):
    """Collector to get failed jobs from Jenkins."""

    def _count_job(self, job: Job) -> bool:
        """Count the job if its build status matches the failure types selected by the user."""
        return self._build_status(job) in self._parameter("failure_type")


class JenkinsUnusedJobs(JenkinsJobs):
    """Collector to get unused jobs from Jenkins."""

    def _count_job(self, job: Job) -> bool:
        """Count the job if its most recent build is too old."""
        age = self._build_age(job)
        max_days = int(cast(str, self._parameter("inactive_days")))
        return age > timedelta(days=max_days) if age < timedelta.max else False
